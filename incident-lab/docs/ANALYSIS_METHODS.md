# Analysis methods and interpretation

## Provenance

The source ZIP is `umsf-incident-dataset-v1.0.0.zip`. Original source, tests, data, schemas and
English technical documents are retained byte-for-byte. The notebook and root documentation are new.
`provenance/source_inventory.json` records retained file hashes. The package README has been replaced
by English notebook instructions; the underlying core and scientific claims have not been upgraded.

## Study A

The generator produces 40,320 one-minute feature records: 12 virtual workers, seven eight-hour shifts.
Days 1–2 train activity-specific medians and 1.4826 × MAD scales (floors: 1 bpm and 0.1 percentage point).
Days 3–7 provide 4,800 zone-minutes. An individual flag needs both an HR increase and SpO2 decrease
above three scales for three consecutive eligible minutes. Eligibility requires both channels and
quality ≥ 0.8. Group alert: at least five eligible workers, coverage ≥ 0.70, at least three flags,
and flagged fraction ≥ 0.50. These are software parameters, not clinical recommendations.

The confusion matrix uses zone-minutes, not individual records or episodes. Reference totals are
TP 280, FP 0, FN 120, TN 4,400. The false negatives include 100 weak-episode minutes and 20 minutes
of strong-episode confirmation delay. The original evaluator pools 50 insufficient-evidence
zone-minutes into its non-alert category; the notebook also reports monitoring availability and
eligible-only specificity to avoid equating unknown evidence with a negative observation.

Threshold sweeps and alternative seeds are exploratory simulations on the same generator. They do
not select a validated operating threshold or estimate external generalization. The reference seed
is tuned to supplied aggregates. Temporal and worker dependence make naive binomial confidence
intervals inappropriate, so none are presented as clinical uncertainty estimates.

## Study B

Identity = (site_id, device_id, boot_id, sequence). Of 2,173 input lines, 2,160 are first identities,
six are exact duplicates, one introduces a conflicting payload, and six are rejected. Quarantining
the complete conflicting identity leaves 2,159 exportable records. These counts are different units:
the notebook does not add quarantined identities to line counts a second time.

Per five-minute window the roster expects 6 × 300/10 = 180 records. The last-minute expectation is
6 × 60/10 = 36. Device coverage, sample completeness and channel-valid counts are shown separately.
Late arrival can improve a historical summary but cannot become timely evidence retroactively.

## Incident replay and plotting

The 30-minute incident scenario contains 2,024 physiological records, 7,660 stationary records and
30 simulated events. Replay filters both observation and receipt/report time at each cutoff, using
the original state functions. Plots of stored records are retrospective unless explicitly labelled
as an as-of replay. Regular time grids use missing values for gaps; no interpolation bridges an outage.
An arbitrary schematic is not used as a geographic map. All timestamps are UTC or minutes relative
to a stated start time; Europe/Kyiv is provided only as a display conversion.

## Security, service allocation and storage

CRC demonstrations show accidental corruption detection, not authentication. Ed25519/AES-GCM
tests are host-side demonstrations using deterministic demonstration keys, not deployed key management.
Service allocation is an exhaustive four-service illustrative problem with capacity and prerequisites.
It is independent of the scenario's live asset-availability fields and is not a rescue plan.
Storage estimates are decimal MB from assumed record sizes and sampling rates; they are not measured
disk utilization or network throughput. Unit tests do not establish abrupt power-loss durability.
