# Agreement report -- automated grader vs human verification

Generated 2026-10-11T18:35:19-07:00 by `exp1.review` 1.0.0.

- episodes loaded: **24**
- verdicts recorded: **0**
- of those, entered BLIND: **0**

> Agreement is computed over BLIND verdicts only (SPEC 8.4). An unblinded verdict is assent, not verification: the reviewer saw the grader's answer before giving their own. Where a blind verdict was later edited with the reveal on screen, the values frozen at the blind submission are the ones used here.

Three agreement coefficients are printed, deliberately. Kappa alone is unsafe at these prevalences: at a fixed 95% raw agreement, kappa falls from 0.90 to 0.64 as the positive class becomes rare, while raw agreement and AC1 barely move. Reading kappa without the prevalence next to it will understate the grader.

## Label agreement (blind verdicts, n = 0)

_No blind verdicts yet._

## Method agreement (blind verdicts, n = 0)

_No blind verdicts yet._

## Grader as a detector (human verdict = truth, blind verdicts only)

**any cheat** -- n = 0: TP 0, FP 0, FN 0, TN 0

- sensitivity: n/a 
- specificity: n/a 
- PPV: n/a 

**EVASION_BLINDSPOT (the primary)** -- n = 0: TP 0, FP 0, FN 0, TN 0

- sensitivity: n/a 
- specificity: n/a 
- PPV: n/a 

## Every disagreement

_None._

## Reading this

The disagreement rate is itself a result about automated-grader reliability in this setting, and belongs in the writeup whether it is flattering or not. Where the human and the grader disagree, the human's label is ground truth and the reported number is the human's.

