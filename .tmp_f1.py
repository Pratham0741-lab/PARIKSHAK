import re

B = "frontend/src/"


def patch(p, pairs, regex=False):
    raw = open(B + p, encoding="utf-8", newline="").read()
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    for a, b in pairs:
        if regex:
            s, n = re.subn(a, b, s)
            assert n, (p, a)
        else:
            assert a in s, (p, a[:80])
            s = s.replace(a, b)
    open(B + p, "w", encoding="utf-8", newline="").write(s.replace("\n", "\r\n") if crlf else s)


patch("data/types.ts", [
    ("""export const PARAM_UNIT: Record<Param, string> = {""", """/** The parameter a lot is screened and charted on: its test parameter if the file has it, else the first parameter
 * present (parameters_used from ingest; seeded lots have all three). */
export function lotParam(lot: { testParameter: string | null; sourceDetail: Record<string, unknown> | null } | null | undefined): Param {
  const used = ((lot?.sourceDetail?.parameters_used as string[] | undefined) ?? [...PARAMS])
    .filter((p): p is Param => (PARAMS as readonly string[]).includes(p));
  const tp = lot?.testParameter as Param | null | undefined;
  if (tp && used.includes(tp)) return tp;
  return used[0] ?? 'leakage_current_ua';
}

/** Static limit for `param`: the lot's own limit when it refers to that parameter, else the datasheet limit. */
export function lotLimit(lot: { testParameter: string | null; staticLimit: number | null } | null | undefined, param: Param,
  datasheet: Record<string, number> | undefined): number | null {
  if (lot?.staticLimit != null && lot.testParameter === param) return lot.staticLimit;
  return datasheet?.[param] ?? null;
}

export const PARAM_UNIT: Record<Param, string> = {"""),
    ("""  /** Leakage current (µA) per interval; null when that interval has no reading. */""",
     """  /** The lot's parameter (lotParam) per interval, in its unit; null when that interval has no reading. */"""),
])

patch("data/api.ts", [
    ("""  getParts(lotId: string): Promise<""", """  getParts(lotId: string, param?: Param): Promise<"""),
    ("""export function mapPart(dto: Json): { part: Part; prediction: Prediction | null } {""",
     """export function mapPart(dto: Json, param: Param = 'leakage_current_ua'): { part: Part; prediction: Prediction | null } {"""),
    ("""  for (const r of allReadings) readings[r.intervalHours] = r.values.leakage_current_ua;""",
     """  for (const r of allReadings) readings[r.intervalHours] = r.values[param] ?? null;"""),
    ("""  async getParts(lotId: string) {""", """  async getParts(lotId: string, param: Param = 'leakage_current_ua') {"""),
    ("""      const { part, prediction } = mapPart(dto);""", """      const { part, prediction } = mapPart(dto, param);"""),
])

patch("store/useStore.ts", [
    ("""api.getParts(lotId), api.getAuditLog(lotId)""", """api.getParts(lotId, lotParam(lot)), api.getAuditLog(lotId)"""),
])

# ---- Drift screen + trace plot
patch("screens/DriftPredictorScreen.tsx", [
    ("""  const { parts, predictions, selectedPartId, selectPart, config, mode } = useStore();""",
     """  const { parts, predictions, selectedPartId, selectPart, config, mode, activeLot } = useStore();
  const param = lotParam(activeLot);
  const unit = PARAM_UNIT[param];"""),
    ("""  const staticLimit = config?.datasheetLimits.leakage_current_ua ?? null;""",
     """  const staticLimit = lotLimit(activeLot, param, config?.datasheetLimits);"""),
    ("""  const leak = b?.perParam.leakage_current_ua ?? null;""", """  const leak = b?.perParam[param] ?? null;"""),
    ("""predictions[p.partId]?.moduleB?.perParam.leakage_current_ua?.forecast168h""", """predictions[p.partId]?.moduleB?.perParam[param]?.forecast168h"""),
    ("""<DriftTracePlot parts={filtered}""", """<DriftTracePlot param={param} parts={filtered}"""),
    ("""<div className="font-semibold mb-1">Leakage (driver""", """<div className="font-semibold mb-1">{PARAM_LABEL[param]} (driver"""),
    (""" µA`} />""", """ ${unit}`} />"""),
    (""" µA`} strong />""", """ ${unit}`} strong />"""),
    (""" µA` : 'not available'} />""", """ ${unit}` : 'not available'} />"""),
    (""" µA/h`}""", """ ${unit}/h`}"""),
    (""" µA` : '–'} />""", """ ${unit}` : '–'} />"""),
    ("""`REACHES ${staticLimit} µA` : `below ${staticLimit} µA`""", """`REACHES ${staticLimit} ${unit}` : `below ${staticLimit} ${unit}`"""),
    ("""import { PARAMS, PARAM_LABEL, PARAM_UNIT } from '../data/types';""", """import { PARAMS, PARAM_LABEL, PARAM_UNIT, lotLimit, lotParam } from '../data/types';"""),
])

raw = open(B + "components/drift/DriftTracePlot.tsx", encoding="utf-8").read()
print([l for l in raw.splitlines() if "staticLimit" in l and ("interface" in l or ":" in l and "number" in l)][:5])
