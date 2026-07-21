# Remote Borne Manager (RBM) - V10 Documentation Overview

This folder contains the consolidated documentation package prepared for the `V10` delivery of `Remote Borne Manager`.

## Deliverable content

- `RBM_V10_Init_Validation_Plan.docx`
- `RBM_V10_Campaign_Validation_Plan.docx`
- `RBM_V10_Campaign_Validation_Plan_Filled.docx`
- `RBM_V10_Client_Guide_Step_By_Step.docx`
- `RBM_V10_Client_Guide_Step_By_Step.pdf`
- `RBM_V10_User_Guide.md`
- `RBM_V10_Revalidation_Test_Plan.md`
- `RBM_V10_Documentation_Requirements.txt`

## V10 functional scope covered by the documentation

- SSH connection management with reconnect handling
- GridCodes remote browser with file and folder navigation
- Remote editing with `Find`, `Save`, and `Save As`
- Edit authentication before opening protected files
- SCP upload and download with hardened transfer flow
- PDF export from remote text files
- Copy to `GridCodes.properties` with optional service restart
- `Energy Manager PRO` with `P/Q` and `CosPhi` modes
- `Restart services`, `Reboot device`, and `Debug logs`
- `Network config` window
- Integrated SSH terminal with history and persistent `cd`
- Temperature and Battery SoC monitoring
- Full right-click context menu in the `GridCodes` browser

## Source mapping

- `RBM_V10_Init_Validation_Plan.docx`
  Source: `documents/PV_RBM_V8_Init.docx`
- `RBM_V10_Campaign_Validation_Plan.docx`
  Source: `documents/RBM_PVAL_v8_CampagneTest.docx`
- `RBM_V10_Campaign_Validation_Plan_Filled.docx`
  Source: `src/documents/RBM_PVAL_v8_CampagneTest_Rempli.docx`
- `RBM_V10_Client_Guide_Step_By_Step.docx`
  Source: `documents/RBM_GUIDE_CLIENT_PAS_A_PAS_V2.docx`
- `RBM_V10_Client_Guide_Step_By_Step.pdf`
  Source: `documents/RBM_GUIDE_CLIENT_PAS_A_PAS_V2.pdf`
- `RBM_V10_User_Guide.md`
  Source base: `documents/USER_GUIDE.md`
- `RBM_V10_Revalidation_Test_Plan.md`
  Source base: `documents/PVAL_TEST_PLAN.md`

## Packaging note

The original project path was read-only in this session. This V10 documentation package was therefore rebuilt in a writable workspace as a clean delivery set, with harmonized names for client-facing use.
