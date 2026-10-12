*==============================================================================
* MOTEUR DE NÉGOCE PHYSIQUE — version Stata (Stata 16 ou plus récent)
*
* Classe les petits/moyens producteurs de pétrole en difficulté et calcule :
*   - un score de détresse et la décote négociable
*   - la probabilité de défaut (modèle de Merton, prix du pétrole simulé par
*     le modèle de Schwartz calibré sur l'historique réel du WTI)
*   - la qualité du brut et le hub de revente le plus rentable (Texas)
*   - le rendement net par baril
*   - une segmentation (k-means) et la détection de profils atypiques
*   - l'allocation optimale (programme linéaire sous contrainte de CVaR)
*   - le wrong-way risk et l'effet de la couverture par futures
*
* Fichiers à mettre dans LE MÊME DOSSIER :
*   moteur_negoce.do, wti_monthly_fred.csv, producteurs_demo.csv
*   (facultatif) fichiers Texas RRC, CSV d'historique de défauts
*
* Utilisation : mets ton dossier dans la ligne « cd » ci-dessous,
*               puis tape dans Stata :  do moteur_negoce.do
* Résultat     : classement_producteurs_stata.xlsx
*==============================================================================
version 16
clear all
set more off
set seed 7

* cd "chemin/vers/le/dossier/stata"      // dossier contenant ce fichier et les données
capture log close _all
log using "journal_moteur.txt", text replace

*------------------------------------------------------------------------------
* 0. PARAMÈTRES (hypothèses à ajuster)
*------------------------------------------------------------------------------
scalar TAUX_FIN     = 0.08   // coût annuel de ta ligne de crédit
scalar JOURS        = 45     // jours entre le paiement (avance) et la revente
scalar LGD          = 0.6    // part de l'avance perdue si le producteur fait défaut
scalar LIGNE_CREDIT = 40     // capital mobilisable pour les avances (millions USD)
scalar CVAR_MAX     = 4      // perte moyenne max. dans les 5 % pires scénarios (MUSD/an)
scalar VOL_IDIO     = 0.25   // volatilité propre à chaque producteur
scalar ANNEES_RES   = 6      // durée de vie économique de la production (années)
scalar TAUX_ACTU    = 0.10   // taux d'actualisation
scalar NSCEN        = 20000  // scénarios Monte Carlo pour les probabilités de défaut
scalar NSCEN_PORT   = 4000   // scénarios pour l'optimisation

global PRODUCTEURS   "producteurs_demo.csv"
global SORTIE        "classement_producteurs_stata.xlsx"
global UTILISER_RRC  0       // 1 = utiliser les fichiers de production du Texas
global FICHIER_LEASE "OG_LEASE_CYCLE_DATA_TABLE.dsv"
global FICHIER_OPER  "OG_OPERATOR_DW_DATA_TABLE.dsv"
global HISTORIQUE    ""      // CSV de défauts réels (colonne defaut = 0/1), facultatif

*------------------------------------------------------------------------------
* PROGRAMMES UTILITAIRES
*------------------------------------------------------------------------------
* Normalise un nom d'entreprise pour rapprocher les fichiers (Texas vs liste)
capture program drop normnom
program define normnom
    args src dst
    quietly {
        gen `dst' = strupper(`src')
        replace `dst' = ustrregexra(`dst', "[^A-Z0-9 ]", " ")
        replace `dst' = ustrregexra(`dst', "\b(INC|LLC|LP|L P|CORP|CORPORATION|CO|COMPANY|LTD|OPERATING|OPERATIONS|ENERGY|RESOURCES|PETROLEUM|OIL|GAS|PRODUCTION|HOLDINGS|THE)\b", " ")
        replace `dst' = stritrim(strtrim(`dst'))
    }
end

* Centre approximatif des districts de la Texas Railroad Commission (variable district)
capture program drop coord_district
program define coord_district
    quietly {
        gen double lat = .
        gen double lon = .
        foreach p in "01 28.9 -98.9" "02 28.8 -97.0" "03 29.8 -95.6" "04 27.5 -98.3" ///
                     "05 32.0 -96.5" "06 32.3 -94.8" "6E 32.4 -94.9" "7B 32.5 -99.7" ///
                     "7C 31.3 -100.9" "08 31.6 -103.0" "8A 33.4 -102.3" "09 33.6 -98.2" ///
                     "10 35.6 -101.0" {
            tokenize "`p'"
            replace lat = `2' if district == "`1'"
            replace lon = `3' if district == "`1'"
        }
    }
end

* Hub de revente optimal = celui qui maximise (prime du hub - coût de transport)
* Primes de hub = ordres de grandeur à brancher sur des cotations réelles
capture program drop calc_hub
program define calc_hub
    coord_district
    quietly {
        gen double best_gain  = .
        gen double best_km    = .
        gen double best_cout  = .
        gen double best_prime = .
        gen str20 hub_revente = "saisie manuelle"
        foreach h in "Midland 31.997 -102.078 0.00" "Cushing 35.985 -96.767 0.60" ///
                     "Houston 29.760 -95.370 1.00" "Corpus_Christi 27.800 -97.396 0.80" {
            tokenize "`h'"
            local nom = subinstr("`1'", "_", " ", .)
            tempvar km cout gain mieux
            gen double `km' = 2*6371*asin(sqrt(sin((`2'-lat)*_pi/360)^2 + ///
                cos(lat*_pi/180)*cos(`2'*_pi/180)*sin((`3'-lon)*_pi/360)^2))
            gen double `cout' = 0.8 + 0.008*`km'*1.25      // fixe + km x détour route
            gen double `gain' = `4' - `cout'
            gen byte `mieux' = !missing(`gain') & (missing(best_gain) | `gain' > best_gain)
            replace hub_revente = "`nom'"  if `mieux'
            replace best_km     = `km'     if `mieux'
            replace best_cout   = `cout'   if `mieux'
            replace best_prime  = `4'      if `mieux'
            replace best_gain   = `gain'   if `mieux'
        }
        drop lat lon
    }
end

*------------------------------------------------------------------------------
* FONCTIONS MATA (calcul stochastique, risque, optimisation)
*------------------------------------------------------------------------------
mata:
// Prix final simulé — modèle de Schwartz 1 facteur, simulation exacte (Ornstein-Uhlenbeck sur ln S)
real colvector prix_final(real scalar s0, real scalar T, real scalar nsteps, real scalar nscen)
{
    k   = st_numscalar("KAPPA")
    sig = st_numscalar("SIGMA")
    mu  = ln(st_numscalar("NIVEAU_LT"))
    dt  = T/nsteps
    a   = exp(-k*dt)
    sd  = sig*sqrt((1 - exp(-2*k*dt))/(2*k))
    x   = J(nscen, 1, ln(s0))
    for (t=1; t<=nsteps; t++) x = x*a :+ mu*(1-a) :+ sd*rnormal(nscen, 1, 0, 1)
    return(exp(x))
}

// Point de défaut KMV : dette court terme + 50 % dette longue - cash
// p = (production, coût de production, dette, dette CT, cash)
real scalar point_defaut(real rowvector p)
{
    return(max((p[4] + 0.5*max((p[3]-p[4], 0)) - p[5], 0)))
}

// Valeur actualisée de la production (MUSD) pour chaque prix simulé
real colvector valeur_actifs(real colvector S, real scalar prod, real scalar cout)
{
    r    = st_numscalar("TAUX_ACTU")
    n    = st_numscalar("ANNEES_RES")
    annu = (1 - (1+r)^(-n))/r
    return(prod*365*rowmax((S :- cout, J(rows(S), 1, 0)))*annu/1e6)
}

// Simulation conjointe prix + défauts (wrong-way risk) — remplit S et D
void defauts_joints(real matrix P, real scalar s0, real scalar nscen, S, D)
{
    vi = st_numscalar("VOL_IDIO")
    S  = prix_final(s0, 1, 12, nscen)
    D  = J(nscen, rows(P), 0)
    for (j=1; j<=rows(P); j++) {
        v    = valeur_actifs(S, P[j,1], P[j,2])
        choc = exp(vi*rnormal(nscen, 1, 0, 1) :- 0.5*vi^2)
        D[., j] = (v :* choc) :< point_defaut(P[j, .])
    }
}

// Distance au défaut (en écarts-types), lecture façon Merton/KMV
real scalar dist_defaut(real rowvector p, real scalar s0)
{
    v0 = valeur_actifs(s0, p[1], p[2])
    if (v0 <= 0) return(.)
    d     = max((point_defaut(p), 1e-6))
    marge = max((s0 - p[2], 1e-6))
    vol   = sqrt((st_numscalar("SIGMA")*s0/marge)^2 + st_numscalar("VOL_IDIO")^2)
    return((ln(v0/d) - 0.5*vol^2)/vol)
}

// VaR et CVaR des pertes (pertes = nombres positifs)
real rowvector var_cvar(real colvector L, real scalar lev)
{
    s = sort(L, 1)
    k = ceil(lev*rows(s))
    return((s[k], mean(s[|k \ rows(s)|])))
}

// P&L annuel (USD) par baril/jour engagé, par scénario et par producteur
real matrix pnl_scenarios(real colvector marge, real matrix D, real scalar s0, real scalar jours, real scalar lgd)
{
    sain = (marge')*365
    defa = (marge')*365*0.5 :- lgd*s0*jours
    un   = J(rows(D), 1, 1)
    return((un*sain) :* (1 :- D) + (un*defa) :* D)
}

// Probabilité qu'au moins la moitié des producteurs du portefeuille fassent défaut ensemble
real scalar proba_moitie(real matrix D, real rowvector w)
{
    act = selectindex(w :> 1)
    if (cols(act) == 0) return(0)
    k = max((1, ceil(cols(act)/2)))
    return(mean(rowsum(D[., act]) :>= k))
}

// Probabilités de défaut Merton + Schwartz pour les producteurs utilisables
void calc_defauts()
{
    P  = st_data(., ("production_bpj", "cout_production_usd_b", "dette_musd", "dette_court_terme_musd", "cash_musd"), "utilisable")
    s0 = st_numscalar("DERNIER_PRIX")
    S  = J(0, 1, .)
    D  = J(0, 0, .)
    defauts_joints(P, s0, st_numscalar("NSCEN"), S, D)
    st_store(., "proba_defaut", "utilisable", mean(D)')
    dd = J(rows(P), 1, .)
    for (j=1; j<=rows(P); j++) dd[j] = dist_defaut(P[j, .], s0)
    st_store(., "distance_au_defaut", "utilisable", dd)
}

// Distance de Mahalanobis : repère les profils atypiques
void mahalanobis()
{
    Z  = st_data(., tokens(st_global("ZVARS")))
    m  = mean(Z)
    Ci = invsym(variance(Z))
    d  = J(rows(Z), 1, .)
    for (i=1; i<=rows(Z); i++) d[i] = (Z[i, .] - m) * Ci * (Z[i, .] - m)'
    st_store(., st_addvar("double", "mahal"), d)
}

// Regroupe les scénarios de défaut identiques : renvoie (lignes uniques, fréquence)
real matrix compresse(real matrix D)
{
    Ds  = sort(D, (1..cols(D)))
    out = J(0, cols(D)+1, .)
    cur = Ds[1, .]
    f   = 1
    for (i=2; i<=rows(Ds); i++) {
        if (Ds[i, .] == cur) f++
        else {
            out = out \ (cur, f)
            cur = Ds[i, .]
            f   = 1
        }
    }
    return(out \ (cur, f))
}

// Allocation optimale (Rockafellar-Uryasev), wrong-way risk, couverture
void portefeuille()
{
    class LinearProgram scalar q
    vars = ("decote_negociee", "ajust_qualite", "cout_logistique", "cout_financement")
    vars = vars, ("prime_risque_juridique", "volume_dispo_bpj", "eligible", "production_bpj")
    vars = vars, ("cout_production_usd_b", "dette_musd", "dette_court_terme_musd", "cash_musd")
    U     = st_data(., vars, "utilisable")
    s0    = st_numscalar("DERNIER_PRIX")
    jours = st_numscalar("JOURS")
    lgd   = st_numscalar("LGD")
    ns    = st_numscalar("NSCEN_PORT")

    S = J(0, 1, .)
    D = J(0, 0, .)
    printf("  [portefeuille] simulation des défauts...\n"); displayflush()
    defauts_joints(U[., 8..12], s0, ns, S, D)
    printf("  [portefeuille] simulation faite\n"); displayflush()

    // Unité de décision : 1 000 barils/jour ; P&L en millions USD par an
    marge = U[., 1] + U[., 2] - U[., 3] - U[., 4] - U[., 5]
    pnl   = pnl_scenarios(marge, D, s0, jours, lgd) / 1000
    n     = cols(pnl)
    cap   = ((U[., 7] :!= 0) :* rowmax((U[., 6], J(rows(U), 1, 0)))) / 1000
    idx   = selectindex(cap :> 0)
    m     = rows(idx)
    xk    = J(1, n, 0)

    if (m == 0) {
        printf("Aucun producteur éligible avec du volume disponible.\n")
    }
    else {
        // Scénarios regroupés : le P&L ne dépend que de QUI fait défaut
        C  = compresse(D)
        Du = C[., 1..cols(D)]
        p  = C[., cols(C)] / ns
        Q  = (pnl_scenarios(marge, Du, s0, jours, lgd) / 1000)[., idx]
        nu = rows(Q)
        // Variables : x (m producteurs), alpha (VaR), z (excès de perte par scénario unique)
        c  = (p' * Q, 0, J(1, nu, 0))
        A1 = (-Q, -J(nu, 1, 1), -I(nu))
        A2 = (J(1, m, 0), 1, p' / 0.05)
        A3 = (J(1, m, s0*jours*1000/1e6), 0, J(1, nu, 0))
        b  = J(nu, 1, 0) \ st_numscalar("CVAR_MAX") \ st_numscalar("LIGNE_CREDIT")
        printf("  [portefeuille] %f scénarios distincts sur %f\n", nu, ns); displayflush()
        q = LinearProgram()
        q.setCoefficients(c)
        q.setMaxOrMin("max")
        q.setInequality((A1 \ A2 \ A3), b)
        q.setBounds((J(1, m, 0), -1000, J(1, nu, 0)), (cap[idx]', 1000, J(1, nu, 1000)))
        val = q.optimize()
        if (q.errorcode() != 0) _error(3498, q.errortext())
        xs = q.parameters()
        xk[idx'] = xs[1..m]
    }

    port = pnl * xk'
    vc   = var_cvar(-port, 0.95)
    st_numscalar("PROFIT", mean(port))
    st_numscalar("VAR95", vc[1])
    st_numscalar("CVAR95", vc[2])
    st_numscalar("CAPITAL", sum(xk)*s0*jours*1000/1e6)
    st_numscalar("PROBA_PERTE", mean(port :< 0))
    st_store(., "allocation_bpj", "utilisable", round(xk' * 1000))

    printf("  [portefeuille] wrong-way risk...\n"); displayflush()
    // Wrong-way risk : mêmes défauts, mais rendus indépendants (on mélange chaque colonne)
    Di = D
    for (j=1; j<=cols(D); j++) Di[., j] = jumble(D[., j])
    pnli = pnl_scenarios(marge, Di, s0, jours, lgd) / 1000
    ref  = (rowmin((cap, J(rows(cap), 1, 2))) :* (cap :> 0))'   // 2 000 b/j chez chaque éligible
    v1 = var_cvar(-(pnl*xk'), 0.95)
    v2 = var_cvar(-(pnli*xk'), 0.95)
    v3 = var_cvar(-(pnl*ref'), 0.95)
    v4 = var_cvar(-(pnli*ref'), 0.95)
    na = sum(xk*1000 :> 1)
    nr = sum(ref*1000 :> 1)
    W = (na, v1[2], proba_moitie(D, xk*1000)) \ (na, v2[2], proba_moitie(Di, xk*1000))
    W = W \ (nr, v3[2], proba_moitie(D, ref*1000)) \ (nr, v4[2], proba_moitie(Di, ref*1000))
    st_matrix("WWR", W)

    printf("  [portefeuille] risque prix...\n"); displayflush()
    // Risque prix d'une cargaison (meilleur deal) : couverte par futures ou non
    mm = st_numscalar("MEILLEURE_MARGE")
    ST = prix_final(s0, jours/365, max((1, floor(jours/5))), st_numscalar("NSCEN"))
    nc = mm :+ (ST :- s0)
    cv = mm :+ rnormal(rows(ST), 1, 0, 0.6)      // risque de base résiduel (hypothèse)
    a1 = var_cvar(-nc, 0.95)
    a2 = var_cvar(-cv, 0.95)
    st_matrix("COUV", (mean(nc), mean(nc :< 0), a1[1], a1[2]) \ (mean(cv), mean(cv :< 0), a2[1], a2[2]))
}
end

*------------------------------------------------------------------------------
* 1. CALIBRATION DU MODÈLE DE PRIX SUR LE WTI RÉEL (FRED MCOILWTICO / EIA)
*    ln S(t+1) = a + b ln S(t) + e   ->  kappa = -ln(b)/dt, niveau LT = exp(a/(1-b))
*------------------------------------------------------------------------------
import delimited using "wti_monthly_fred.csv", clear varnames(1) stringcols(1)
rename date datestr
gen mdate = mofd(date(datestr, "YMD"))
format mdate %tm
tsset mdate
sort mdate
scalar DERNIER_PRIX = wti[_N]
gen double x = ln(wti)

* Échantillon 2015-2026 (régime de prix post-schiste). Première paire : 2015m1 -> 2015m2
regress x L.x if mdate >= tm(2015m2)
scalar CAL_B  = _b[L.x]
scalar CAL_A  = _b[_cons]
scalar CAL_S  = e(rmse)
scalar CAL_SE = _se[L.x]
scalar KAPPA      = -ln(scalar(CAL_B))*12
scalar NIVEAU_LT  = exp(scalar(CAL_A)/(1 - scalar(CAL_B)))
* Correction : des moyennes mensuelles lissent la volatilité (facteur racine de 3/2)
scalar SIGMA      = scalar(CAL_S)*sqrt(2*scalar(KAPPA)/(1 - scalar(CAL_B)^2))*sqrt(1.5)
scalar DEMI_VIE   = ln(2)/scalar(KAPPA)*12
scalar KAPPA_BAS  = -ln(min(scalar(CAL_B) + 1.96*scalar(CAL_SE), 0.9999))*12
scalar KAPPA_HAUT = -ln(scalar(CAL_B) - 1.96*scalar(CAL_SE))*12

di _n as txt "=== Calibration du modèle de Schwartz (WTI 2015-2026) ==="
di as txt "kappa (retour à la moyenne) : " as res %6.4f KAPPA ///
   as txt "   IC 95 % : [" as res %5.3f KAPPA_BAS as txt " ; " as res %5.3f KAPPA_HAUT as txt "]"
di as txt "niveau de long terme (USD/b): " as res %6.2f NIVEAU_LT
di as txt "volatilité annuelle         : " as res %6.4f SIGMA
di as txt "demi-vie (mois)             : " as res %6.1f DEMI_VIE
di as txt "dernier prix WTI (USD/b)    : " as res %6.2f DERNIER_PRIX

*------------------------------------------------------------------------------
* 2. (FACULTATIF) PRODUCTION DU TEXAS — Railroad Commission, Production Data Query Dump
*    Production des 12 derniers mois, déclin vs 12 mois précédents, district principal
*------------------------------------------------------------------------------
if $UTILISER_RRC == 1 {
    import delimited using "$FICHIER_LEASE", delimiters("}") varnames(1) stringcols(_all) clear
    keep operator_no cycle_year_month lease_oil_prod_vol district_no
    destring lease_oil_prod_vol, replace force
    replace lease_oil_prod_vol = 0 if missing(lease_oil_prod_vol)
    replace district_no = strupper(strtrim(district_no))
    replace district_no = "0" + district_no if strlen(district_no) == 1

    * District principal = celui où l'opérateur produit le plus
    preserve
    collapse (sum) oil = lease_oil_prod_vol, by(operator_no district_no)
    bysort operator_no (oil): keep if _n == _N
    keep operator_no district_no
    rename district_no district_rrc
    tempfile districts
    save `districts'
    restore

    collapse (sum) oil = lease_oil_prod_vol, by(operator_no cycle_year_month)
    egen int mois = group(cycle_year_month)
    quietly summarize mois
    local M = r(max)
    if `M' < 24 {
        di as error "Il faut au moins 24 mois de données Texas pour calculer le déclin."
        exit 459
    }
    gen byte periode = cond(mois >= `M' - 11, 2, cond(mois >= `M' - 23, 1, 0))
    drop if periode == 0
    collapse (sum) oil, by(operator_no periode)
    reshape wide oil, i(operator_no) j(periode)
    replace oil1 = 0 if missing(oil1)
    replace oil2 = 0 if missing(oil2)
    gen double production_rrc    = round(oil2/365)
    gen double declin_annuel_pct = round((oil2/oil1 - 1)*100, 0.1) if oil1 > 0
    merge 1:1 operator_no using `districts', keep(master match) nogenerate

    preserve
    import delimited using "$FICHIER_OPER", delimiters("}") varnames(1) stringcols(_all) clear
    keep operator_no operator_name
    duplicates drop operator_no, force
    tempfile noms
    save `noms'
    restore
    merge 1:1 operator_no using `noms', keep(master match) nogenerate

    * Qualité du brut par zone (API, soufre %) — WTI Midland, Eagle Ford : vérifiés ; autres : estimations
    gen zone_brut = ""
    replace zone_brut = "Eagle Ford"             if inlist(district_rrc, "01", "02", "04")
    replace zone_brut = "Côte du Golfe Texas"    if district_rrc == "03"
    replace zone_brut = "Est Texas"              if inlist(district_rrc, "05", "06", "6E")
    replace zone_brut = "Panhandle / Nord Texas" if inlist(district_rrc, "7B", "09", "10")
    replace zone_brut = "WTI Midland"            if inlist(district_rrc, "7C", "08", "8A")
    gen double api_rrc    = .
    gen double soufre_rrc = .
    replace api_rrc = 47.7 if zone_brut == "Eagle Ford"
    replace soufre_rrc = 0.10 if zone_brut == "Eagle Ford"
    replace api_rrc = 37 if zone_brut == "Côte du Golfe Texas"
    replace soufre_rrc = 0.30 if zone_brut == "Côte du Golfe Texas"
    replace api_rrc = 39 if inlist(zone_brut, "Est Texas", "Panhandle / Nord Texas")
    replace soufre_rrc = 0.30 if zone_brut == "Est Texas"
    replace soufre_rrc = 0.40 if zone_brut == "Panhandle / Nord Texas"
    replace api_rrc = 42 if zone_brut == "WTI Midland"
    replace soufre_rrc = 0.20 if zone_brut == "WTI Midland"
    gen double ajust_qualite_usd_b = -cond(api_rrc < 35, (35 - api_rrc)*0.15, ///
        cond(api_rrc > 45, (api_rrc - 45)*0.10, 0)) - soufre_rrc*0.6

    gen district = district_rrc
    calc_hub
    gen double gain_net_hub_usd_b = round(best_gain, 0.01)
    rename hub_revente hub_optimal
    drop best_* district
    normnom operator_name cle
    save "rrc_tous_operateurs.dta", replace

    * Liste de prospection : 500-20 000 b/j et production en baisse de plus de 15 %
    keep if inrange(production_rrc, 500, 20000) & declin_annuel_pct <= -15
    sort declin_annuel_pct
    save "prospects_texas.dta", replace

    use "rrc_tous_operateurs.dta", clear
    bysort cle (production_rrc): keep if _n == _N
    save "rrc_operateurs.dta", replace
}

*------------------------------------------------------------------------------
* 3. DONNÉES DES PRODUCTEURS
*------------------------------------------------------------------------------
import delimited using "$PRODUCTEURS", clear varnames(1) encoding("utf-8") stringcols(15)
capture confirm string variable district
if _rc {
    capture drop district
    gen str4 district = ""
}
replace district = strupper(strtrim(district))
replace district = "0" + district if strlen(district) == 1

if $UTILISER_RRC == 1 {
    normnom producteur cle
    merge m:1 cle using "rrc_operateurs.dta", keep(master match) nogenerate ///
        keepusing(production_rrc declin_annuel_pct district_rrc api_rrc soufre_rrc)
    replace production_bpj = production_rrc if !missing(production_rrc)
    replace api            = api_rrc        if !missing(api_rrc)
    replace soufre_pct     = soufre_rrc     if !missing(soufre_rrc)
    replace district       = district_rrc   if district_rrc != ""
    drop production_rrc api_rrc soufre_rrc district_rrc cle
}

*------------------------------------------------------------------------------
* 4. SCORING
*------------------------------------------------------------------------------
gen double dette_ebitda  = dette_musd / max(ebitda_musd, 1)
gen double couverture_ct = cash_musd / max(dette_court_terme_musd, 1)

* Score de détresse 0-100 (besoin de cash du producteur -> décote négociable)
gen double score_detresse = min(max(dette_ebitda/8, 0), 1)*45 ///
    + min(max(1 - couverture_ct, 0), 1)*35 + going_concern*20
capture confirm variable declin_annuel_pct
if !_rc {
    replace score_detresse = score_detresse + min(max(-declin_annuel_pct/30, 0), 1)*15 ///
        if !missing(declin_annuel_pct)
}
replace score_detresse = min(score_detresse, 100)

* Probabilité de défaut : Merton + Schwartz si production et coût connus, sinon heuristique
gen byte utilisable = !missing(production_bpj) & !missing(cout_production_usd_b)
gen double proba_defaut = 0.01 + (score_detresse/100)^2*0.35
gen methode_defaut = "heuristique"
replace methode_defaut = "Merton + Schwartz" if utilisable
gen double distance_au_defaut = .
quietly count if utilisable
if r(N) > 0 {
    mata: calc_defauts()
}

gen double decote_negociee = 1 + score_detresse/100*7
gen double ajust_qualite   = -cond(api < 35, (35 - api)*0.15, cond(api > 45, (api - 45)*0.10, 0)) ///
    - soufre_pct*0.6

* Logistique : hub optimal si le district texan est connu, sinon distance saisie
calc_hub
gen double cout_logistique = cond(!missing(best_km), best_cout - best_prime, 0.8 + distance_hub_km*0.006)
replace distance_hub_km = round(best_km) if !missing(best_km)
drop best_*

gen double cout_financement       = scalar(DERNIER_PRIX)*scalar(TAUX_FIN)*scalar(JOURS)/365
gen double perte_attendue         = proba_defaut*scalar(LGD)*scalar(DERNIER_PRIX)*scalar(JOURS)/365
gen double prime_risque_juridique = risque_juridique - 1
gen double rendement_net_usd_b = decote_negociee + ajust_qualite - cout_logistique ///
    - cout_financement - perte_attendue - prime_risque_juridique
gen double volume_dispo_bpj = round(production_bpj*volume_non_engage_pct)

gen byte eligible = risque_juridique < 4
gen decision = cond(!eligible, "EXCLU (conformité)", ///
    cond(rendement_net_usd_b >= 3 & proba_defaut < 0.25, "Cible prioritaire", ///
    cond(rendement_net_usd_b > 0, "À surveiller", "Pas rentable")))

*------------------------------------------------------------------------------
* 5. APPRENTISSAGE STATISTIQUE : segmentation, anomalies, modèle de défaut
*------------------------------------------------------------------------------
local feats dette_ebitda couverture_ct api soufre_pct cout_logistique proba_defaut
capture confirm variable declin_annuel_pct
if !_rc local feats `feats' declin_annuel_pct
foreach v of local feats {
    quietly summarize `v', detail
    quietly gen double z_`v' = cond(missing(`v'), r(p50), `v')
    quietly summarize z_`v'
    if r(sd) > 0 & !missing(r(sd)) {
        quietly replace z_`v' = (z_`v' - r(mean))/r(sd)
    }
    else {
        quietly replace z_`v' = 0
    }
}
unab zvars : z_*
global ZVARS "`zvars'"

* k-means sur variables standardisées -> profils sain / tendu / critique
local k = min(3, _N)
cluster kmeans $ZVARS, k(`k') name(seg) start(krandom(12345))
bysort seg: egen double m_score = mean(score_detresse)
egen rang = group(m_score)
gen segment = cond(rang == 1, "Profil sain", cond(rang == 2, "Profil tendu", "Profil critique"))
drop m_score rang

* Profils atypiques (distance de Mahalanobis) -> à vérifier en priorité (conformité)
mata: mahalanobis()
gen anomalie = ""
quietly summarize mahal
if _N < 20 {
    replace anomalie = "Profil atypique : vérifier" if mahal == r(max)
}
else {
    _pctile mahal, p(90)
    replace anomalie = "Profil atypique : vérifier" if mahal >= r(r1)
}

* Modèle de défaut supervisé (logit) — seulement avec un historique RÉEL de défauts
if "$HISTORIQUE" != "" {
    preserve
    import delimited using "$HISTORIQUE", clear varnames(1)
    logit defaut dette_ebitda couverture_ct api soufre_pct cout_logistique
    lroc, nograph
    scalar AUC = r(area)
    estimates store modele_defaut
    restore
    estimates restore modele_defaut
    predict double proba_defaut_logit, pr
}

*------------------------------------------------------------------------------
* 6. PORTEFEUILLE OPTIMAL, WRONG-WAY RISK, COUVERTURE
*------------------------------------------------------------------------------
gen double allocation_bpj = 0
quietly summarize rendement_net_usd_b if eligible
scalar MEILLEURE_MARGE = r(max)
mata: portefeuille()

*------------------------------------------------------------------------------
* 7. EXPORT EXCEL
*------------------------------------------------------------------------------
gsort -eligible -rendement_net_usd_b
foreach v of varlist score_detresse proba_defaut distance_au_defaut decote_negociee ajust_qualite ///
        cout_logistique cout_financement perte_attendue rendement_net_usd_b dette_ebitda couverture_ct {
    quietly replace `v' = round(`v', 0.001)
}
local cols producteur pays decision allocation_bpj segment anomalie score_detresse proba_defaut ///
    methode_defaut distance_au_defaut decote_negociee ajust_qualite hub_revente distance_hub_km ///
    cout_logistique cout_financement perte_attendue prime_risque_juridique rendement_net_usd_b ///
    volume_dispo_bpj dette_ebitda couverture_ct api soufre_pct
foreach v in declin_annuel_pct proba_defaut_logit {
    capture confirm variable `v'
    if !_rc local cols `cols' `v'
}
export excel `cols' using "$SORTIE", sheet("Classement") firstrow(variables) replace

* Portefeuille optimal
putexcel set "$SORTIE", sheet("Portefeuille optimal") modify
putexcel A1 = "Indicateur" B1 = "Valeur"
local i = 2
foreach item in "Profit espéré sur 1 an (MUSD)|PROFIT" "VaR 95 % (MUSD)|VAR95" ///
        "CVaR 95 % (MUSD)|CVAR95" "Capital immobilisé (MUSD)|CAPITAL" ///
        "Probabilité de perte sur 1 an|PROBA_PERTE" "Plafond CVaR (MUSD)|CVAR_MAX" ///
        "Ligne de crédit (MUSD)|LIGNE_CREDIT" {
    gettoken lab sc : item, parse("|")
    local sc = subinstr("`sc'", "|", "", .)
    local val = round(scalar(`sc'), 0.001)
    putexcel A`i' = "`lab'" B`i' = `val'
    local ++i
}

* Wrong-way risk
putexcel set "$SORTIE", sheet("Wrong-way risk") modify
putexcel A1 = "Portefeuille" B1 = "Défauts" C1 = "Producteurs" D1 = "CVaR 95 % (MUSD)" ///
    E1 = "Proba défaut de la moitié ou plus"
putexcel A2 = "Optimal" B2 = "Liés au prix (réaliste)" A3 = "Optimal" B3 = "Indépendants (naïf)"
putexcel A4 = "Diversifié de référence" B4 = "Liés au prix (réaliste)"
putexcel A5 = "Diversifié de référence" B5 = "Indépendants (naïf)"
putexcel C2 = matrix(WWR)

* Risque prix
putexcel set "$SORTIE", sheet("Risque prix") modify
putexcel A1 = "Stratégie (meilleur deal, par baril)" B1 = "Gain moyen USD/b" C1 = "Proba de perte" ///
    D1 = "VaR 95 % USD/b" E1 = "CVaR 95 % USD/b"
putexcel A2 = "Non couvert" A3 = "Couvert par futures"
putexcel B2 = matrix(COUV)

* Calibration et hypothèses
putexcel set "$SORTIE", sheet("Calibration et hypothèses") modify
putexcel A1 = "Paramètre" B1 = "Valeur"
local i = 2
foreach item in "kappa (retour à la moyenne)|KAPPA" "kappa IC 95 % bas|KAPPA_BAS" ///
        "kappa IC 95 % haut|KAPPA_HAUT" "Niveau de long terme USD/b|NIVEAU_LT" ///
        "Volatilité annuelle|SIGMA" "Demi-vie (mois)|DEMI_VIE" "Dernier prix WTI USD/b|DERNIER_PRIX" ///
        "Taux de financement|TAUX_FIN" "Jours de portage|JOURS" "Perte en cas de défaut|LGD" ///
        "Volatilité propre producteur|VOL_IDIO" {
    gettoken lab sc : item, parse("|")
    local sc = subinstr("`sc'", "|", "", .)
    local val = round(scalar(`sc'), 0.0001)
    putexcel A`i' = "`lab'" B`i' = `val'
    local ++i
}
putexcel A`i' = "Source prix" B`i' = "FRED MCOILWTICO (EIA), moyenne mensuelle, 2015-2026"
local ++i
putexcel A`i' = "Producteurs" B`i' = "$PRODUCTEURS"
capture confirm scalar AUC
if !_rc {
    local ++i
    local val = round(scalar(AUC), 0.001)
    putexcel A`i' = "AUC du logit (dans l'échantillon)" B`i' = `val'
}

* Qualités de brut de référence
putexcel set "$SORTIE", sheet("Qualités de brut") modify
putexcel A1 = "Brut" B1 = "API" C1 = "Soufre %" D1 = "Source"
putexcel A2 = "WTI Midland" B2 = 42 C2 = 0.20 D2 = "vérifié (Platts)"
putexcel A3 = "Eagle Ford" B3 = 47.7 C3 = 0.10 D3 = "vérifié (Auers)"
putexcel A4 = "Bakken" B4 = 42 C4 = 0.15 D4 = "vérifié (Auers)"
putexcel A5 = "WCS (Alberta lourd)" B5 = 21 C5 = 3.5 D5 = "vérifié (spéc. WCS)"
putexcel A6 = "Brent / Mer du Nord" B6 = 38 C6 = 0.40 D6 = "estimation"
putexcel A7 = "Côte du Golfe Texas" B7 = 37 C7 = 0.30 D7 = "estimation"
putexcel A8 = "Est Texas" B8 = 39 C8 = 0.30 D8 = "estimation"
putexcel A9 = "Panhandle / Nord Texas" B9 = 39 C9 = 0.40 D9 = "estimation"

* Prospects Texas
if $UTILISER_RRC == 1 {
    preserve
    use "prospects_texas.dta", clear
    export excel operator_no operator_name production_rrc declin_annuel_pct district_rrc zone_brut ///
        api_rrc soufre_rrc ajust_qualite_usd_b hub_optimal gain_net_hub_usd_b ///
        using "$SORTIE", sheet("Prospects Texas", replace) firstrow(variables)
    restore
}

*------------------------------------------------------------------------------
* 8. RÉSUMÉ À L'ÉCRAN
*------------------------------------------------------------------------------
di _n as txt "=== Classement ==="
list producteur decision segment proba_defaut rendement_net_usd_b hub_revente allocation_bpj, ///
    noobs abbreviate(20) separator(0)
di _n as txt "=== Portefeuille optimal ==="
di as txt "Profit espéré (MUSD/an) : " as res %8.2f PROFIT
di as txt "CVaR 95 % (MUSD)        : " as res %8.2f CVAR95
di as txt "Capital immobilisé      : " as res %8.2f CAPITAL
di as txt "Probabilité de perte    : " as res %8.3f PROBA_PERTE
di _n as txt "Wrong-way risk (lignes : optimal réaliste, optimal naïf, diversifié réaliste, diversifié naïf)"
matrix colnames WWR = producteurs cvar95 proba_moitie
matrix list WWR, noheader format(%9.3f)
di _n as txt "Risque prix (lignes : non couvert, couvert)"
matrix colnames COUV = gain_moyen proba_perte var95 cvar95
matrix list COUV, noheader format(%9.3f)
di _n as txt "Résultats enregistrés dans : " as res "$SORTIE"
log close
