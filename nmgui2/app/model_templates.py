"""
NONMEM control-file templates for the "New model" action.

Templates are plain strings using str.format() with three substitution tokens:
  {stem}      — the file stem chosen by the user (e.g. "run1")
  {problem}   — a human-readable version of stem used in $PROBLEM
  {data_path} — path to the dataset file (e.g. "../data.csv")

IMPORTANT: standard NONMEM record bodies do not use curly braces, so
str.format() is safe here.  If you add a template that contains a literal
brace (e.g. NONMEM 7.5 JSON output blocks), escape it as {{ or }}.

Adding a new template
---------------------
1. Add an entry to TEMPLATES with a descriptive key (templates are listed in
   insertion order — put new entries at the logical location in the dict).
2. That is all — the NewModelDialog populates its combobox from TEMPLATES.keys().

Sources
-------
The ODE-based templates (ADVAN6) are adapted from:
  Certara, "Trial Simulator for NONMEM Modelers — Examples Guide", v1, Dec 2018.
  ($SIMULATION blocks replaced with $ESTIMATION/$COVARIANCE; combined residual
  error model and diagonal OMEGA used instead of pure-proportional with OMEGA BLOCK.)
"""

# ── Shared building blocks ────────────────────────────────────────────────────

_HEADER = """\
$PROBLEM  {problem}

$INPUT    ID TIME DV AMT MDV EVID CMT

$DATA     {data_path} IGNORE=@

"""

# Variant headers for models that need extra dataset columns
_HEADER_RATE = """\
$PROBLEM  {problem}

; NOTE: dataset must include a RATE column with RATE=-2 on dosing rows
;       (NONMEM uses D1/ALAG1 in $PK to define duration/lag of zero-order input)
$INPUT    ID TIME DV AMT MDV EVID CMT RATE

$DATA     {data_path} IGNORE=@

"""

_HEADER_DVID = """\
$PROBLEM  {problem}

; NOTE: dataset must include a DVID column (1=plasma, 2=urine) and EVID=2 rows
;       to reset the urine compartment after each urine observation.
$INPUT    ID TIME DV AMT MDV EVID CMT DVID

$DATA     {data_path} IGNORE=@

"""


def _tail(*eta_names: str) -> str:
    """
    Return the estimation/covariance/table tail block.
    eta_names lists the ETA column names for $TABLE, e.g. 'ETA1', 'ETA2', ...
    {stem} is left as a format placeholder for render() to fill in.
    """
    etas = ' '.join(eta_names) + (' ' if eta_names else '')
    return (
        '$ESTIMATION METHOD=COND INTER MAXEVAL=9999 PRINT=5\n\n'
        '$COVARIANCE UNCOND PRINT=E MATRIX=R\n\n'
        '$TABLE    ID TIME DV IPRED CWRES ' + etas + '\\\n'
        '          NOPRINT NOAPPEND ONEHEADER FILE={stem}.tab\n'
    )


# ── Templates ─────────────────────────────────────────────────────────────────

TEMPLATES = {}

# ==============================================================================
# ANALYTICAL SUBROUTINE TEMPLATES  (ADVAN1/2/3/4 — linear PK)
# ==============================================================================

# ---------- Blank ---------------------------------------------------------------
TEMPLATES['$PRED subroutine blank'] = (
    _HEADER
    + """\
$PRED
  ; ---------- Model code here ----------
  ; THETA(1) = placeholder parameter
  ; ETA(1)   = inter-individual variability
  ; EPS(1)   = residual error

  IPRED = THETA(1) * EXP(ETA(1))
  Y     = IPRED * (1 + EPS(1)) + EPS(2)

$THETA
  (0, 1)       ; 1 PLACEHOLDER

$OMEGA
  0.1          ; 1 IIV placeholder

$SIGMA
  0.1          ; 1 Proportional RUV
  1            ; 2 Additive RUV

"""
    + _tail('ETA1')
)

# ---------- 1-CMT oral ----------------------------------------------------------
TEMPLATES['1-CMT oral (ADVAN2 TRANS2)'] = (
    _HEADER
    + """\
$SUBROUTINES ADVAN2 TRANS2

$PK
  KA = THETA(1) * EXP(ETA(1))   ; Absorption rate constant (1/h)
  CL = THETA(2) * EXP(ETA(2))   ; Clearance (L/h)
  V  = THETA(3) * EXP(ETA(3))   ; Volume of distribution (L)
  S2 = V / 1000                 ; Scaling (AMT in mg, DV in ng/mL)

$ERROR
  IPRED = F
  W     = SQRT((THETA(4)*IPRED)**2 + THETA(5)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  1)      ; 1 KA  (1/h)
  (0,  5)      ; 2 CL  (L/h)
  (0, 50)      ; 3 V   (L)
  (0,  0.2)    ; 4 Proportional error coefficient
  (0,  1)      ; 5 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV KA
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV V

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3')
)

# ---------- 1-CMT IV bolus ------------------------------------------------------
TEMPLATES['1-CMT IV bolus (ADVAN1 TRANS2)'] = (
    _HEADER
    + """\
$SUBROUTINES ADVAN1 TRANS2

$PK
  CL = THETA(1) * EXP(ETA(1))   ; Clearance (L/h)
  V  = THETA(2) * EXP(ETA(2))   ; Volume of distribution (L)
  S1 = V / 1000                 ; Scaling (AMT in mg, DV in ng/mL)

$ERROR
  IPRED = F
  W     = SQRT((THETA(3)*IPRED)**2 + THETA(4)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 CL  (L/h)
  (0, 50)      ; 2 V   (L)
  (0,  0.2)    ; 3 Proportional error coefficient
  (0,  1)      ; 4 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV CL
  0.1          ; 2 IIV V

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2')
)

# ---------- 2-CMT oral ----------------------------------------------------------
TEMPLATES['2-CMT oral (ADVAN4 TRANS4)'] = (
    _HEADER
    + """\
$SUBROUTINES ADVAN4 TRANS4

$PK
  KA  = THETA(1) * EXP(ETA(1))  ; Absorption rate constant (1/h)
  CL  = THETA(2) * EXP(ETA(2))  ; Clearance (L/h)
  Q   = THETA(3)                 ; Inter-compartmental clearance (L/h)
  V2  = THETA(4) * EXP(ETA(3))  ; Central volume (L)
  V3  = THETA(5)                 ; Peripheral volume (L)
  S2  = V2 / 1000               ; Scaling (AMT in mg, DV in ng/mL)

$ERROR
  IPRED = F
  W     = SQRT((THETA(6)*IPRED)**2 + THETA(7)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,   1)     ; 1 KA  (1/h)
  (0,  10)     ; 2 CL  (L/h)
  (0,   5)     ; 3 Q   (L/h)
  (0,  50)     ; 4 V2  (L)
  (0, 100)     ; 5 V3  (L)
  (0,   0.2)   ; 6 Proportional error coefficient
  (0,   1)     ; 7 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV KA
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV V2

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3')
)

# ---------- 2-CMT IV bolus ------------------------------------------------------
TEMPLATES['2-CMT IV bolus (ADVAN3 TRANS4)'] = (
    _HEADER
    + """\
$SUBROUTINES ADVAN3 TRANS4

$PK
  CL  = THETA(1) * EXP(ETA(1))  ; Clearance (L/h)
  Q   = THETA(2)                 ; Inter-compartmental clearance (L/h)
  V1  = THETA(3) * EXP(ETA(2))  ; Central volume (L)
  V2  = THETA(4)                 ; Peripheral volume (L)
  S1  = V1 / 1000               ; Scaling (AMT in mg, DV in ng/mL)

$ERROR
  IPRED = F
  W     = SQRT((THETA(5)*IPRED)**2 + THETA(6)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  10)     ; 1 CL  (L/h)
  (0,   5)     ; 2 Q   (L/h)
  (0,  50)     ; 3 V1  (L)
  (0, 100)     ; 4 V2  (L)
  (0,   0.2)   ; 5 Proportional error coefficient
  (0,   1)     ; 6 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV CL
  0.1          ; 2 IIV V1

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2')
)


# ==============================================================================
# ODE-BASED TEMPLATES — TIER 1  (ADVAN6 + $DES — non-linear / TMDD / complex)
# ==============================================================================

# ---------- 1-CMT Michaelis-Menten elimination IV --------------------------------
TEMPLATES['1-CMT Michaelis-Menten IV (ADVAN6)'] = (
    _HEADER
    + """\
; Michaelis-Menten (non-linear) elimination — IV bolus
; Use when linear clearance fails (e.g. saturable enzymes, high-dose biologics)
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 1
  COMP  = (CENTRAL)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKM   = THETA(2)
  KM     = TVKM   * EXP(ETA(2))  ; MM concentration — half-max elim rate (mg/L)
  TVVMAX = THETA(3)
  VMAX   = TVVMAX * EXP(ETA(3))  ; Maximum elimination rate (mg/h)
  S1     = V / 1000              ; Scaling (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -VMAX * A(1) / (KM * V + A(1))

$ERROR
  IPRED = A(1) / V
  W     = SQRT((THETA(4)*IPRED)**2 + THETA(5)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV    (L)
  (0,  1)      ; 2 TVKM   (mg/L)
  (0,  2)      ; 3 TVVMAX (mg/h)
  (0,  0.2)    ; 4 Proportional error coefficient
  (0,  1)      ; 5 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KM
  0.1          ; 3 IIV VMAX

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3')
)

# ---------- 1-CMT Michaelis-Menten elimination oral ------------------------------
TEMPLATES['1-CMT Michaelis-Menten oral (ADVAN6)'] = (
    _HEADER
    + """\
; Michaelis-Menten elimination with first-order oral absorption
; Use when linear clearance fails and drug is administered orally
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 2
  COMP  = (ABSORB)
  COMP  = (CENTRAL)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKM   = THETA(2)
  KM     = TVKM   * EXP(ETA(2))  ; MM concentration — half-max elim rate (mg/L)
  TVVMAX = THETA(3)
  VMAX   = TVVMAX * EXP(ETA(3))  ; Maximum elimination rate (mg/h)
  TVKA   = THETA(4)
  KA     = TVKA   * EXP(ETA(4))  ; Absorption rate constant (1/h)
  S2     = V / 1000              ; Scaling (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -KA * A(1)
  DADT(2) =  KA * A(1) - VMAX * A(2) / (KM * V + A(2))

$ERROR
  IPRED = A(2) / V
  W     = SQRT((THETA(5)*IPRED)**2 + THETA(6)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV    (L)
  (0,  1)      ; 2 TVKM   (mg/L)
  (0,  2)      ; 3 TVVMAX (mg/h)
  (0,  1)      ; 4 TVKA   (1/h)
  (0,  0.2)    ; 5 Proportional error coefficient
  (0,  1)      ; 6 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KM
  0.1          ; 3 IIV VMAX
  0.1          ; 4 IIV KA

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4')
)

# ---------- 2-CMT time-varying clearance oral ------------------------------------
TEMPLATES['2-CMT time-varying CL oral — sigmoid Imax (ADVAN6)'] = (
    _HEADER
    + """\
; 2-compartment model with sigmoid Imax time-varying clearance (oral absorption)
; CL(t) = BASECL * (1 - IMAX * t^GAM / (t^GAM + T50^GAM))
; Use for enzyme induction/inhibition, circadian CL, or disease-mediated CL changes
; Ref: Certara TS Guide §2.C
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (CENTRAL)
  COMP  = (PERIPH)
  COMP  = (ABSORP)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Central volume of distribution (L)
  TVCL   = THETA(2)
  BASECL = TVCL   * EXP(ETA(2))  ; Baseline (maximum) clearance (L/h)
  TVV2   = THETA(3)
  V2     = TVV2   * EXP(ETA(3))  ; Peripheral volume (L)
  TVCL2  = THETA(4)
  CL2    = TVCL2  * EXP(ETA(4))  ; Inter-compartmental clearance (L/h)
  TVKA   = THETA(5)
  KA     = TVKA   * EXP(ETA(5))  ; Absorption rate constant (1/h)
  ; --- Sigmoid Imax parameters (clearance inhibited over time) ---
  TVLOGITIMAX  = THETA(6)
  LOGITIMAX    = TVLOGITIMAX + ETA(6)      ; logit-normal IIV on IMAX
  IMAX         = EXP(LOGITIMAX) / (1 + EXP(LOGITIMAX))  ; Max inhibition fraction (0-1)
  TVT50        = THETA(7)
  T50          = TVT50  * EXP(ETA(7))     ; Time of half-maximum inhibition (h)
  TVGAM        = THETA(8)
  GAM          = TVGAM  * EXP(ETA(8))     ; Hill coefficient (steepness)
  S1           = V / 1000                 ; Scaling (AMT in mg, DV in ng/mL)

$DES
  ; Time-varying clearance (sigmoid Imax inhibition)
  CL      = BASECL * (1 - IMAX * T**GAM / (T**GAM + T50**GAM))
  DADT(1) = KA * A(3) - CL / V * A(1) - CL2 * (A(1)/V - A(2)/V2)
  DADT(2) = CL2 * (A(1)/V - A(2)/V2)
  DADT(3) = -KA * A(3)

$ERROR
  IPRED = A(1) / V
  W     = SQRT((THETA(9)*IPRED)**2 + THETA(10)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1  TVV          (L)
  (0,  1)      ; 2  TVCL         (L/h)
  (0,  3)      ; 3  TVV2         (L)
  (0,  0.5)    ; 4  TVCL2        (L/h)
  (0,  0.6)    ; 5  TVKA         (1/h)
  1.5          ; 6  TVLOGITIMAX  (logit scale; ~0.82 on probability scale)
  (0,  2)      ; 7  TVT50        (h)
  (0,  3)      ; 8  TVGAM
  (0,  0.2)    ; 9  Proportional error coefficient
  (0,  1)      ; 10 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV CL (BASECL)
  0.1          ; 3 IIV V2
  0.1          ; 4 IIV CL2
  0.1          ; 5 IIV KA
  0.1          ; 6 IIV LOGITIMAX
  0.1          ; 7 IIV T50
  0.1          ; 8 IIV GAM

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4', 'ETA5')
)

# ---------- QE-TMDD 1-CMT IV -----------------------------------------------------
TEMPLATES['QE-TMDD 1-CMT IV (ADVAN6)'] = (
    _HEADER
    + """\
; Quasi-equilibrium TMDD model — 1 compartment, IV bolus
; Standard starting model for monoclonal antibodies and biologics
;
; State variables:
;   A(1) = total drug (ligand) amount in central compartment (nmol)
;   A(2) = total receptor (target) concentration (nM)
;
; Free drug concentration uses the QE approximation:
;   C = 0.5*((Ctot - Rtot - KD) + SQRT((Ctot - Rtot - KD)^2 + 4*KD*Ctot))
;
; Units: V in L, AMT in nmol → concentration in nM throughout.
;        DV = free drug concentration (nM). No scaling needed if units are consistent.
; Ref: Certara TS Guide §3.A
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 2
  COMP  = (TOTLIG)   ; Total ligand (drug) amount
  COMP  = (TOTRECP)  ; Total receptor concentration

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKEL  = THETA(2)
  KEL    = TVKEL  * EXP(ETA(2))  ; First-order elimination rate constant (1/h)
  TVR_0  = THETA(3)
  R_0    = TVR_0                  ; Baseline receptor concentration (nM)
  TVKD   = THETA(4)
  KD     = TVKD                   ; Dissociation constant (nM)
  TVKINT = THETA(5)
  KINT   = TVKINT                 ; Drug-receptor complex internalization rate (1/h)
  TVKSYN = THETA(6)
  KSYN   = TVKSYN                 ; Receptor synthesis rate (nM/h)
  KDEG   = KSYN / R_0             ; Receptor baseline degradation rate (1/h)
  ; Initial condition: receptor at steady-state
  A_0(2) = R_0

$DES
  CTOT = A(1) / V
  RTOT = A(2)
  ; Free drug concentration (QE approximation)
  C    = 0.5 * ((CTOT - RTOT - KD) + SQRT((CTOT - RTOT - KD)**2 + 4 * KD * CTOT))
  ; Total drug amount in central compartment
  DADT(1) = -KINT * A(1) - (KEL - KINT) * C * V
  ; Total receptor concentration
  DADT(2) = KSYN - KDEG * A(2) - (KINT - KDEG) * (CTOT - C)

$ERROR
  C_TOT = A(1) / V
  R_TOT = A(2)
  IPRED = 0.5 * ((C_TOT - R_TOT - KD) + SQRT((C_TOT - R_TOT - KD)**2 + 4 * KD * C_TOT))
  W     = SQRT((THETA(7)*IPRED)**2 + THETA(8)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  0.9)    ; 1 TVV      (L)
  (0,  0.002)  ; 2 TVKEL    (1/h)
  (0, 400)     ; 3 TVR_0    (nM)
  (0,  0.001)  ; 4 TVKD     (nM)
  (0,  0.001)  ; 5 TVKINT   (1/h)
  (0,  0.22)   ; 6 TVKSYN   (nM/h)
  (0,  0.2)    ; 7 Proportional error coefficient
  (0,  0.01)   ; 8 Additive error (nM)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KEL

; Note: SAEM may converge better than FOCE-I for this model type
$ESTIMATION METHOD=COND INTER MAXEVAL=9999 PRINT=5

$COVARIANCE UNCOND PRINT=E MATRIX=R

$TABLE    ID TIME DV IPRED CWRES ETA1 ETA2 \\
          NOPRINT NOAPPEND ONEHEADER FILE={stem}.tab
"""
)

# ---------- Wagner 1-CMT IV — TMDD, Rtot constant --------------------------------
TEMPLATES['Wagner 1-CMT IV — TMDD Rtot constant (ADVAN6)'] = (
    _HEADER
    + """\
; Wagner TMDD approximation — 1 compartment, IV bolus, Rtot assumed constant
; Simpler alternative to full QE-TMDD when KINT ≈ KDEG (receptor turnover slow)
;
; Free drug: C = 0.5*((Ctot - Rtot - KD) + SQRT((Ctot - Rtot - KD)^2 + 4*KD*Ctot))
; RTOT is estimated as a fixed parameter (no receptor ODE).
;
; Units: V in L, AMT in nmol → concentration in nM. DV = free drug (nM).
; Ref: Certara TS Guide §3.E
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 1
  COMP  = (CENTRAL)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKEL  = THETA(2)
  KEL    = TVKEL  * EXP(ETA(2))  ; First-order elimination rate constant (1/h)
  TVRTOT = THETA(3)
  RTOT   = TVRTOT                 ; Total receptor concentration, assumed constant (nM)
  TVKD   = THETA(4)
  KD     = TVKD                   ; Dissociation constant (nM)
  TVKINT = THETA(5)
  KINT   = TVKINT                 ; Internalization rate constant (1/h)

$DES
  CTOT = A(1) / V
  C    = 0.5 * ((CTOT - RTOT - KD) + SQRT((CTOT - RTOT - KD)**2 + 4 * KD * CTOT))
  DADT(1) = -KINT * A(1) - (KEL - KINT) * C * V

$ERROR
  C_TOT = A(1) / V
  IPRED = 0.5 * ((C_TOT - RTOT - KD) + SQRT((C_TOT - RTOT - KD)**2 + 4 * KD * C_TOT))
  W     = SQRT((THETA(6)*IPRED)**2 + THETA(7)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  0.9)    ; 1 TVV    (L)
  (0,  0.002)  ; 2 TVKEL  (1/h)
  (0, 400)     ; 3 TVRTOT (nM)
  (0,  0.001)  ; 4 TVKD   (nM)
  (0,  0.001)  ; 5 TVKINT (1/h)
  (0,  0.2)    ; 6 Proportional error coefficient
  (0,  0.01)   ; 7 Additive error (nM)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KEL

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2')
)

# ---------- Dual first-order absorption (simultaneous) ---------------------------
TEMPLATES['Dual first-order absorption 1-CMT (ADVAN6)'] = (
    _HEADER
    + """\
; 1-CMT model with two simultaneous first-order absorption pathways
; Use for biphasic/irregular oral absorption (e.g. enteric-coated, dual-peak profiles)
;
; DATASET NOTE: each dosing event requires TWO dose records at the same time:
;   one with CMT=1 (pathway 1) and one with CMT=2 (pathway 2).
;   F1 and F2 (reserved variables) fraction the dose: F1 + F2 = 1.
; Ref: Certara TS Guide §5.A.1
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (ABSORB1)  ; First absorption compartment
  COMP  = (ABSORB2)  ; Second absorption compartment
  COMP  = (CENTRAL)

$PK
  TVV  = THETA(1)
  V    = TVV  * EXP(ETA(1))   ; Volume of distribution (L)
  TVCL = THETA(2)
  CL   = TVCL * EXP(ETA(2))   ; Clearance (L/h)
  TVKA1 = THETA(3)
  KA1  = TVKA1 * EXP(ETA(3))  ; Absorption rate — pathway 1 (1/h)
  TVKA2 = THETA(4)
  KA2  = TVKA2 * EXP(ETA(4))  ; Absorption rate — pathway 2 (1/h)
  ; Fraction absorbed via pathway 1 (logit-normal parameterisation)
  TVLOGITF1 = THETA(5)
  LOGITF1   = TVLOGITF1
  F1        = EXP(LOGITF1) / (1 + EXP(LOGITF1))
  F2        = 1 - F1
  S3        = V / 1000         ; Scaling (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -KA1 * A(1)                          ; Absorption pathway 1
  DADT(2) = -KA2 * A(2)                          ; Absorption pathway 2
  DADT(3) =  KA1 * A(1) + KA2 * A(2) - CL / V * A(3)  ; Central

$ERROR
  IPRED = A(3) / V
  W     = SQRT((THETA(6)*IPRED)**2 + THETA(7)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV       (L)
  (0,  1)      ; 2 TVCL      (L/h)
  (0,  0.5)    ; 3 TVKA1     (1/h) — fast pathway
  (0,  1.5)    ; 4 TVKA2     (1/h) — slow pathway
  0.1          ; 5 TVLOGITF1 (logit; ~0.52 on probability scale for F1)
  (0,  0.2)    ; 6 Proportional error coefficient
  (0,  1)      ; 7 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV KA1
  0.1          ; 4 IIV KA2

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4')
)

# ---------- Parallel first-order absorption + lag on second pathway --------------
TEMPLATES['Parallel first-order absorption + lag 1-CMT (ADVAN6)'] = (
    _HEADER
    + """\
; 1-CMT model with two first-order absorption pathways, lag time on pathway 2
; Use for dual-peak profiles where second peak is delayed (parallel input with lag)
;
; DATASET NOTE: each dosing event requires TWO dose records at the same time:
;   one with CMT=1 (pathway 1) and one with CMT=2 (pathway 2 — lagged by ALAG2).
;   F1 and F2 fraction the dose; ALAG2 is the absorption lag for pathway 2.
; Ref: Certara TS Guide §5.B
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (ABSORB1)  ; First absorption compartment (no lag)
  COMP  = (ABSORB2)  ; Second absorption compartment (lag = ALAG2)
  COMP  = (CENTRAL)

$PK
  TVV  = THETA(1)
  V    = TVV  * EXP(ETA(1))   ; Volume of distribution (L)
  TVCL = THETA(2)
  CL   = TVCL * EXP(ETA(2))   ; Clearance (L/h)
  TVKA1 = THETA(3)
  KA1  = TVKA1 * EXP(ETA(3))  ; Absorption rate — pathway 1 (1/h)
  TVKA2 = THETA(4)
  KA2  = TVKA2 * EXP(ETA(4))  ; Absorption rate — pathway 2 (1/h)
  TVALAG2 = THETA(5)
  ALAG2   = TVALAG2 * EXP(ETA(5))  ; Lag time for pathway 2 (h)
  ; Fraction absorbed via pathway 1 (logit-normal)
  TVLOGITF1 = THETA(6)
  LOGITF1   = TVLOGITF1
  F1        = EXP(LOGITF1) / (1 + EXP(LOGITF1))
  F2        = 1 - F1
  S3        = V / 1000         ; Scaling (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -KA1 * A(1)
  DADT(2) = -KA2 * A(2)
  DADT(3) =  KA1 * A(1) + KA2 * A(2) - CL / V * A(3)

$ERROR
  IPRED = A(3) / V
  W     = SQRT((THETA(7)*IPRED)**2 + THETA(8)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV        (L)
  (0,  1)      ; 2 TVCL       (L/h)
  (0,  0.5)    ; 3 TVKA1      (1/h)
  (0,  1.5)    ; 4 TVKA2      (1/h)
  (0,  1)      ; 5 TVALAG2    (h)
  0.1          ; 6 TVLOGITF1  (logit scale)
  (0,  0.2)    ; 7 Proportional error coefficient
  (0,  1)      ; 8 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV KA1
  0.1          ; 4 IIV KA2
  0.1          ; 5 IIV ALAG2

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4', 'ETA5')
)


# ==============================================================================
# ODE-BASED TEMPLATES — TIER 2  (specialist / context-specific)
# ==============================================================================

# ---------- QE-TMDD 1-CMT oral ---------------------------------------------------
TEMPLATES['QE-TMDD 1-CMT oral (ADVAN6)'] = (
    _HEADER
    + """\
; QE-TMDD model — 1 compartment, first-order oral/SC absorption
; Use for subcutaneously administered biologics with target-mediated disposition
;
; NOTE: in this formulation A(1) is total drug CONCENTRATION (nmol/L = nM),
;       A(2) is absorption compartment AMOUNT (nmol),
;       A(3) is total receptor CONCENTRATION (nM).
; Units: AMT in nmol, V in L → concentration in nM. DV = free drug (nM).
; Ref: Certara TS Guide §3.C
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (CENTRAL)  ; Total drug concentration (nM) — NOTE: A(1) = concentration
  COMP  = (ABSORP)   ; Absorption compartment amount (nmol)
  COMP  = (TOTRECP)  ; Total receptor concentration (nM)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKEL  = THETA(2)
  KEL    = TVKEL  * EXP(ETA(2))  ; Elimination rate constant (1/h)
  TVR_0  = THETA(3)
  R_0    = TVR_0                  ; Baseline receptor concentration (nM)
  TVKD   = THETA(4)
  KD     = TVKD                   ; Dissociation constant (nM)
  TVKINT = THETA(5)
  KINT   = TVKINT                 ; Internalization rate constant (1/h)
  TVKA   = THETA(6)
  KA     = TVKA   * EXP(ETA(3))  ; Absorption rate constant (1/h)
  TVKSYN = THETA(7)
  KSYN   = TVKSYN                 ; Receptor synthesis rate (nM/h)
  KDEG   = KSYN / R_0             ; Receptor degradation rate constant (1/h)
  ; Initial condition: receptor at baseline
  A_0(3) = R_0

$DES
  CTOT = A(1)           ; A(1) is concentration (nM), not amount
  RTOT = A(3)
  C    = 0.5 * ((CTOT - RTOT - KD) + SQRT((CTOT - RTOT - KD)**2 + 4 * KD * CTOT))
  DADT(1) = KA * A(2) / V - KINT * A(1) - (KEL - KINT) * C
  DADT(2) = -KA * A(2)
  DADT(3) = KSYN - KDEG * A(3) - (KINT - KDEG) * (CTOT - C)

$ERROR
  C_TOT = A(1)
  R_TOT = A(3)
  IPRED = 0.5 * ((C_TOT - R_TOT - KD) + SQRT((C_TOT - R_TOT - KD)**2 + 4 * KD * C_TOT))
  W     = SQRT((THETA(8)*IPRED)**2 + THETA(9)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  0.9)    ; 1 TVV    (L)
  (0,  0.002)  ; 2 TVKEL  (1/h)
  (0, 400)     ; 3 TVR_0  (nM)
  (0,  0.001)  ; 4 TVKD   (nM)
  (0,  0.001)  ; 5 TVKINT (1/h)
  (0,  0.2)    ; 6 TVKA   (1/h)
  (0,  0.22)   ; 7 TVKSYN (nM/h)
  (0,  0.2)    ; 8 Proportional error coefficient
  (0,  0.01)   ; 9 Additive error (nM)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KEL
  0.1          ; 3 IIV KA

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3')
)

# ---------- QE-TMDD 2-CMT IV -----------------------------------------------------
TEMPLATES['QE-TMDD 2-CMT IV (ADVAN6)'] = (
    _HEADER
    + """\
; QE-TMDD model — 2 compartments, IV bolus
; Use when peripheral distribution is significant alongside TMDD
;
; State variables:
;   A(1) = total drug amount in central compartment (nmol)
;   A(2) = free drug amount in peripheral compartment (nmol)
;   A(3) = total receptor concentration in central compartment (nM)
;
; Units: V in L, AMT in nmol → nM throughout. DV = free drug (nM).
; Ref: Certara TS Guide §3.B
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (CENTRAL)  ; Total drug amount (nmol)
  COMP  = (PERIPH)   ; Free drug amount in peripheral (nmol)
  COMP  = (TOTRECP)  ; Total receptor concentration (nM)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Central volume (L)
  TVKEL  = THETA(2)
  KEL    = TVKEL  * EXP(ETA(2))  ; Elimination rate constant (1/h)
  TVR_0  = THETA(3)
  R_0    = TVR_0                  ; Baseline receptor concentration (nM)
  TVKD   = THETA(4)
  KD     = TVKD                   ; Dissociation constant (nM)
  TVKINT = THETA(5)
  KINT   = TVKINT                 ; Internalization rate constant (1/h)
  TVKCP  = THETA(6)
  KCP    = TVKCP  * EXP(ETA(3))  ; Central → peripheral rate (1/h)
  TVKPC  = THETA(7)
  KPC    = TVKPC  * EXP(ETA(4))  ; Peripheral → central rate (1/h)
  TVKSYN = THETA(8)
  KSYN   = TVKSYN                 ; Receptor synthesis rate (nM/h)
  KDEG   = KSYN / R_0
  A_0(3) = R_0

$DES
  CTOT = A(1) / V
  RTOT = A(3)
  C    = 0.5 * ((CTOT - RTOT - KD) + SQRT((CTOT - RTOT - KD)**2 + 4 * KD * CTOT))
  DADT(1) = -KINT * A(1) - (KEL - KINT) * C * V - KCP * C * V + KPC * A(2)
  DADT(2) = KCP * C * V - KPC * A(2)
  DADT(3) = KSYN - KDEG * A(3) - (KINT - KDEG) * (CTOT - C)

$ERROR
  C_TOT = A(1) / V
  R_TOT = A(3)
  IPRED = 0.5 * ((C_TOT - R_TOT - KD) + SQRT((C_TOT - R_TOT - KD)**2 + 4 * KD * C_TOT))
  W     = SQRT((THETA(9)*IPRED)**2 + THETA(10)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  0.9)    ; 1  TVV    (L)
  (0,  0.002)  ; 2  TVKEL  (1/h)
  (0, 400)     ; 3  TVR_0  (nM)
  (0,  0.001)  ; 4  TVKD   (nM)
  (0,  0.001)  ; 5  TVKINT (1/h)
  (0,  0.03)   ; 6  TVKCP  (1/h)
  (0,  0.009)  ; 7  TVKPC  (1/h)
  (0,  0.22)   ; 8  TVKSYN (nM/h)
  (0,  0.2)    ; 9  Proportional error coefficient
  (0,  0.01)   ; 10 Additive error (nM)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KEL
  0.1          ; 3 IIV KCP
  0.1          ; 4 IIV KPC

; Note: SAEM may converge better than FOCE-I for this model type
$ESTIMATION METHOD=COND INTER MAXEVAL=9999 PRINT=5

$COVARIANCE UNCOND PRINT=E MATRIX=R

$TABLE    ID TIME DV IPRED CWRES ETA1 ETA2 ETA3 ETA4 \\
          NOPRINT NOAPPEND ONEHEADER FILE={stem}.tab
"""
)

# ---------- Zero-order absorption + MM elimination -------------------------------
TEMPLATES['Zero-order absorption + MM elimination (ADVAN6)'] = (
    _HEADER_RATE
    + """\
; 1-CMT model, zero-order absorption (infusion-like), Michaelis-Menten elimination
; Use for controlled/extended-release formulations or slow-dissolving drugs
;
; DATASET NOTE: add RATE=-2 on each dosing row. Duration D1 is estimated in $PK.
;               RATE=-2 tells NONMEM to use D1 (defined in $PK) as infusion duration.
; Ref: Certara TS Guide §4.C
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 1
  COMP  = (CENTRAL)

$PK
  TVV    = THETA(1)
  V      = TVV    * EXP(ETA(1))  ; Volume of distribution (L)
  TVKM   = THETA(2)
  KM     = TVKM   * EXP(ETA(2))  ; MM concentration — half-max elim rate (mg/L)
  TVVMAX = THETA(3)
  VMAX   = TVVMAX * EXP(ETA(3))  ; Maximum elimination rate (mg/h)
  ; Duration of zero-order absorption (estimated parameter)
  TVD1   = THETA(4)
  D1     = TVD1   * EXP(ETA(4))  ; Absorption duration (h)
  S1     = V / 1000              ; Scaling (AMT in mg, DV in ng/mL)

$DES
  ; Input is zero-order (AMT/D1 per hour) — handled by NONMEM via D1 + RATE=-2
  DADT(1) = -VMAX * A(1) / (KM * V + A(1))

$ERROR
  IPRED = A(1) / V
  W     = SQRT((THETA(5)*IPRED)**2 + THETA(6)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV    (L)
  (0,  1)      ; 2 TVKM   (mg/L)
  (0,  2)      ; 3 TVVMAX (mg/h)
  (0,  6)      ; 4 TVD1   (h) — absorption duration
  (0,  0.2)    ; 5 Proportional error coefficient
  (0,  1)      ; 6 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV KM
  0.1          ; 3 IIV VMAX
  0.1          ; 4 IIV D1

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4')
)

# ---------- Simultaneous first-order + zero-order absorption ---------------------
TEMPLATES['Simultaneous first+zero order absorption 1-CMT (ADVAN6)'] = (
    _HEADER_RATE
    + """\
; 1-CMT model with simultaneous first-order AND zero-order absorption
; Use for mixed-release formulations (e.g. immediate + extended-release combination)
;
; DATASET NOTE: each dosing event requires TWO dose records at the same time:
;   Record 1: CMT=1, RATE=0  → first-order absorption (fraction F1 of dose)
;   Record 2: CMT=2, RATE=-2 → zero-order absorption (fraction F2 = 1-F1, duration D2)
;   F1/F2 are reserved variables fractionating the dose to each CMT.
; Ref: Certara TS Guide §5.C
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 2
  COMP  = (ABSORP)   ; First-order absorption depot
  COMP  = (CENTRAL)  ; Also receives zero-order input (via D2/F2 on CMT=2)

$PK
  TVV  = THETA(1)
  V    = TVV  * EXP(ETA(1))   ; Volume of distribution (L)
  TVCL = THETA(2)
  CL   = TVCL * EXP(ETA(2))   ; Clearance (L/h)
  TVKA = THETA(3)
  KA   = TVKA * EXP(ETA(3))   ; First-order absorption rate constant (1/h)
  ; Duration of zero-order absorption process
  TVD2 = THETA(4)
  D2   = TVD2 * EXP(ETA(4))   ; Zero-order absorption duration (h)
  ; Fraction of dose absorbed first-order (logit-normal)
  TVLOGITF1 = THETA(5)
  LOGITF1   = TVLOGITF1
  F1        = EXP(LOGITF1) / (1 + EXP(LOGITF1))
  F2        = 1 - F1
  S2        = V / 1000         ; Scaling (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -KA * A(1)                   ; First-order absorption depot → central
  DADT(2) =  KA * A(1) - CL / V * A(2)  ; Central (zero-order input via D2/CMT2 implicit)

$ERROR
  IPRED = A(2) / V
  W     = SQRT((THETA(6)*IPRED)**2 + THETA(7)**2)
  IRES  = DV - IPRED
  IWRES = IRES / W
  Y     = IPRED + W * EPS(1)

$THETA
  (0,  5)      ; 1 TVV       (L)
  (0,  1)      ; 2 TVCL      (L/h)
  (0,  2.5)    ; 3 TVKA      (1/h)
  (0,  6)      ; 4 TVD2      (h) — zero-order duration
  0.1          ; 5 TVLOGITF1 (logit; ~0.52 probability for F1)
  (0,  0.2)    ; 6 Proportional error coefficient
  (0,  1)      ; 7 Additive error (ng/mL)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV KA
  0.1          ; 4 IIV D2

$SIGMA
  1 FIX        ; 1 Auxiliary (scaled by W in $ERROR)

"""
    + _tail('ETA1', 'ETA2', 'ETA3', 'ETA4')
)

# ---------- 2-CMT IV + urine compartment -----------------------------------------
TEMPLATES['2-CMT IV + urine compartment (ADVAN6)'] = (
    _HEADER_DVID
    + """\
; 2-CMT IV model with urine compartment for dual plasma+urine observations
; Use for renal excretion studies where both plasma concentration and
; cumulative urinary excretion are measured
;
; DATASET NOTE:
;   DVID=1 → plasma concentration observation (DV in ng/mL)
;   DVID=2 → urine amount observation (DV in mg)
;   After each urine observation add two EVID=2 rows to reset A(3):
;     Row 1: CMT=-3, EVID=2  (reset urine compartment to zero)
;     Row 2: CMT= 3, EVID=2  (re-enable accumulation)
;   Two separate EPS terms for plasma (EPS(1)) and urine (EPS(2)).
; Ref: Certara TS Guide §4.A
$SUBROUTINES ADVAN6 TOL=6

$MODEL
  NCOMP = 3
  COMP  = (CENTRAL)  ; Drug amount in central compartment
  COMP  = (PERIPH)   ; Drug amount in peripheral compartment
  COMP  = (URINE)    ; Cumulative urinary drug amount (reset after each urine obs)

$PK
  TVV   = THETA(1)
  V     = TVV   * EXP(ETA(1))   ; Central volume of distribution (L)
  TVCL  = THETA(2)
  CL    = TVCL  * EXP(ETA(2))   ; Total systemic clearance (L/h)
  TVV2  = THETA(3)
  V2    = TVV2  * EXP(ETA(3))   ; Peripheral volume (L)
  TVCL2 = THETA(4)
  CL2   = TVCL2 * EXP(ETA(4))   ; Inter-compartmental clearance (L/h)
  S1    = V / 1000              ; Scaling for plasma (AMT in mg, DV in ng/mL)

$DES
  DADT(1) = -CL / V * A(1) - CL2 * (A(1)/V - A(2)/V2)  ; Central
  DADT(2) =  CL2 * (A(1)/V - A(2)/V2)                   ; Peripheral
  DADT(3) =  CL  / V * A(1)                              ; Urine accumulation

$ERROR
  IF (DVID .EQ. 1) THEN
    IPRED = A(1) / V
    W     = SQRT((THETA(5)*IPRED)**2 + THETA(6)**2)
    Y     = IPRED + W * EPS(1)
  ENDIF
  IF (DVID .EQ. 2) THEN
    IPRED = A(3)
    W     = SQRT((THETA(7)*IPRED)**2 + THETA(8)**2)
    Y     = IPRED + W * EPS(2)
  ENDIF
  IRES  = DV - IPRED
  IWRES = IRES / W

$THETA
  (0,  5)      ; 1 TVV   (L)
  (0,  1)      ; 2 TVCL  (L/h) — total systemic clearance
  (0,  3)      ; 3 TVV2  (L)
  (0,  0.5)    ; 4 TVCL2 (L/h)
  (0,  0.2)    ; 5 Proportional error — plasma
  (0,  1)      ; 6 Additive error — plasma (ng/mL)
  (0,  0.2)    ; 7 Proportional error — urine
  (0,  1)      ; 8 Additive error — urine (mg)

$OMEGA
  0.1          ; 1 IIV V
  0.1          ; 2 IIV CL
  0.1          ; 3 IIV V2
  0.1          ; 4 IIV CL2

$SIGMA
  1 FIX        ; 1 Auxiliary — plasma  (scaled by W in $ERROR)
  1 FIX        ; 2 Auxiliary — urine   (scaled by W in $ERROR)

$ESTIMATION METHOD=COND INTER MAXEVAL=9999 PRINT=5

$COVARIANCE UNCOND PRINT=E MATRIX=R

$TABLE    ID TIME DV DVID IPRED CWRES ETA1 ETA2 ETA3 ETA4 \\
          NOPRINT NOAPPEND ONEHEADER FILE={stem}.tab
"""
)


# ── Public API ────────────────────────────────────────────────────────────────

def template_names() -> list[str]:
    """Return the list of template names in display order."""
    return list(TEMPLATES.keys())


def render(template_name: str, stem: str, data_path: str = '../data.csv') -> str:
    """
    Return a fully rendered NONMEM control file as a string.

    Parameters
    ----------
    template_name : str
        Key from TEMPLATES (use template_names() to enumerate).
    stem : str
        File stem (no extension) — used in $TABLE FILE= and $PROBLEM.
    data_path : str
        Path written into the $DATA record.
    """
    template = TEMPLATES.get(template_name, TEMPLATES['$PRED subroutine blank'])
    problem  = stem.replace('_', ' ').replace('-', ' ')
    return template.format(stem=stem, data_path=data_path, problem=problem)
