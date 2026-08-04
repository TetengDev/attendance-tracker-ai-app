# Face Recognition Evaluation Corpora

This document outlines the evaluation datasets used to evaluate the face recognition engine, establish the FAR/FRR curve, and tune the similarity threshold.

## Tiered Dataset Strategy

We employ a tiered dataset strategy based on license, domain match (cooperative kiosk setting vs. in-the-wild), and volume.

### 1. NIST SD32 MEDS-II (Primary)
* **Status**: Primary dataset for initial sweep.
* **License**: NIST open license (US Government work, public domain, no commercial restriction).
* **Format**: Frontal, cooperative, controlled-lighting captures matching a kiosk setup.
* **Why**: The subject matches our domain perfectly and is deceased (reducing biometric privacy concerns).
* **Action**: Requires manual registration to obtain.

### 2. DigiFace-1M (Supplementary)
* **Status**: Supplementary dataset.
* **License**: R-UDA (Restricted Use Data Agreement) — **Non-commercial use only**.
* **Format**: Synthetic face images (10K identities × 72 images each).
* **Why**: Very clean synthetic data structure, but commercial constraints prevent it from being primary.
* **Action**: Requires accepting R-UDA terms manually.

### 3. LFW (Labeled Faces in the Wild)
* **Status**: Nightly regression tripwire only.
* **License**: No formal license (scraped copyrighted news photographs).
* **Why**: Saturated (modern models achieve 99.85%+ accuracy). Useful only to verify that preprocessing or alignment did not break. **Never use LFW to derive a production threshold**.

### 4. SFHQ-T2I (Impostor Gallery Padding)
* **Status**: Impostor gallery padding.
* **License**: MIT License.
* **Why**: Generates high-quality synthetic faces without identity labels. Used to pad the impostor gallery size to $N = 5000$ to extrapolate False Accept Rate (FAR) under scale.

---

## Prohibited / Withdrawn Datasets

The following datasets are **explicitly prohibited** due to ethical, privacy, or licensing violations:
* **MS-Celeb-1M** (Withdrawn 2019)
* **VGGFace2** (Withdrawn)
* **MegaFace** (Decommissioned 2020)
* **CASIA-WebFace** (Withdrawn / unavailable from origin)
* **IJB-A / IJB-B / IJB-C** (NIST discontinued distribution)

*Any script or manual process attempting to fetch these datasets will fail loudly.*

---

## How to Acquire the Corpora

### SFHQ-T2I (Automated)
Run the script to download a subset of the pravsels/SFHQ_256 dataset (MIT licensed) for gallery padding:
```bash
bash infra/fetch_evalsets.sh
```

### NIST SD32 MEDS-II (Manual)
1. Go to the [NIST MEDS-II page](https://www.nist.gov/itl/iad/image-group/special-database-32-multiple-encounter-dataset-meds).
2. Request access and download the dataset.
3. Place the images in `fixtures/faces/meds2/`.

### DigiFace-1M (Manual)
1. Visit the [DigiFace-1M GitHub Page](https://github.com/microsoft/DigiFace1M).
2. Accept the R-UDA terms and download the dataset shards.
3. Extract them to `fixtures/faces/digiface/`.
