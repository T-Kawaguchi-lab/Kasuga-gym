#!/usr/bin/env python
# coding: utf-8

# # ガントチャートのみ出力　制約式完成版


# In[50]:
# ============================================================
# 必要なライブラリの読み込み
# ============================================================
import argparse #configの引数を受け入れるため
import logging #ログを整った形で出力のため
import yaml #config.yamlを読み込むため
from pathlib import Path #パス操作を安全にするため
from ortools.sat.python import cp_model #OR-Tools CP-SATのモデルを読み込むため
import pandas as pd #CSVなどのデータを処理のため
from datetime import date #年月日の計算のため
import calendar #年月日の計算のため
import json #preferences.json,events.jsonの読み込むため
import shutil #ファイルのコピーのため

# ============================================================
# CLI引数（ターミナルで実行する際に後ろに付ける追加情報のこと）
# CLI化はターミナルからコマンド入力1発で実行できるようにすること。
# 誰のPCでも同じ手順で動かせ、自動化しやすい。また、設定を引数で変更できる。
# ============================================================
def parse_args(): #CLI引数を定義
    p = argparse.ArgumentParser(description="Kasuga gym scheduling optimizer (CP-SAT)") #引数の仕様書を作る
    p.add_argument("--config", type=str, default=None,
                   help="設定ファイル（未指定なら repo直下の config.yaml）") #--cinfig(設定ファイルを指定する場合)
    p.add_argument("--out", type=str, default="output",
                   help="出力フォルダ（相対パスは repo直下基準）") #--out(出力フォルダを指定する場合)
    p.add_argument("--no-gantt", action="store_true",
                   help="ガント等の画像出力をスキップ（CSVは出力）") #--no-gant(画像出力をしない場合)
    p.add_argument("--log", type=str, default=None,
                   help="ログ出力先（未指定なら output/YYYY-MM/run.log）") #--log(ログファイルを出力する場合)
    p.add_argument("--data-tag", type=str, default=None,
               help="data配下の月フォルダ名（例: 2026-01）。未指定なら configのyear/monthから自動")
    p.add_argument("--data-dir", type=str, default=None,
               help="入力JSONフォルダを直接指定（この中に preferences.json / events.json を置く）")
    return p.parse_args()

ARGS = parse_args() #CLI引数を読む

def _resolve_path(base_dir: Path, path_str: str | None, default_rel: str) -> Path: #CLI引数があれば使いなければ元のものを使う
    """相対パスは repo直下(base_dir)基準で解決"""
    if not path_str:
        return (base_dir / default_rel).resolve()
    p = Path(path_str)
    return p.resolve() if p.is_absolute() else (base_dir / p).resolve()

def save_run_snapshot(out_run_dir: Path, config_path: Path, pref_path: Path, event_path: Path): #使用した入力データと設定データのコピーを保存する
    """
    実行時の入力・設定を output/YYYY-MM/ に保存して証跡を残す。
    """
    out_run_dir.mkdir(parents=True, exist_ok=True) #出力先フォルダがなければ作る

    shutil.copy2(config_path, out_run_dir / "config_used.yaml") #コピーを作る
    shutil.copy2(pref_path, out_run_dir / "preferences_used.json")
    shutil.copy2(event_path, out_run_dir / "events_used.json")

    print(f"[INFO] Snapshot saved -> {out_run_dir}")

# ============================================================
# SETTINGS（config.yamlより）
# ============================================================
BASE_DIR = Path(__file__).resolve().parents[1]   # Kasuga-gym-systemをリポジトリの基本フォルダとする
CONFIG_PATH = _resolve_path(BASE_DIR, ARGS.config, "config.yaml") #設定ファイルの絶対パス
OUT_DIR = _resolve_path(BASE_DIR, ARGS.out, "output") #出力フォルダの絶対パス
NO_GANTT = bool(ARGS.no_gantt) #画像出力をするかどうか
with open(CONFIG_PATH, "r", encoding="utf-8") as f: #config.yaml(設定ファイル)の読み込み
    config = yaml.safe_load(f)

YEAR = int(config["year"]) #対象年
MONTH = int(config["month"]) #対象月

slot = 30  #1スロットを30分に指定
MIN_SLOTS = int(config["min_slots"]) #MIN_SLOTS = 3   # 条件① 利用最低時間は1時間30分
MAX_SOLVE_SECONDS = int(config["max_solve_seconds"]) #MAX_SOLVE_SECONDS = 60   #計算に使う時間

TEAM_W = 10000 #使用団体最大化の重み
DAILY_SPREAD_W = 100      #1日の利用時間差のための重み
DAILY_SPREAD_EV_W = DAILY_SPREAD_W  # 日公平性（イベント日）の重み
PROP_MONTH_W = 13  # 月合計公平性の重み
MORN_SPREAD_W = 10  #  朝公平性の重み
PROP_ZONE_W = 10  #時間帯別公平性の重み
IDLE_W = 100000  # 空き時間(未割当)ペナルティの重み

#出力先フォルダの作成
RUN_TAG = f"{YEAR:04d}-{MONTH:02d}"   # 例: "2026-01"
OUT_RUN_DIR = OUT_DIR / RUN_TAG
OUT_RUN_DIR.mkdir(parents=True, exist_ok=True) #すでにあってもエラーにならない

# dataの読み込み
DATA_BASE_DIR = BASE_DIR / "data"

if ARGS.data_dir:
    # data-dir が指定されたらそれを優先
    DATA_DIR = _resolve_path(BASE_DIR, ARGS.data_dir, default_rel="data")
elif ARGS.data_tag:
    # data-tag が指定されたら data/<tag>/ を使う
    DATA_DIR = (DATA_BASE_DIR / ARGS.data_tag).resolve()
else:
    # ★何も指定がなければ config year/month に自動追従
    DATA_DIR = (DATA_BASE_DIR / RUN_TAG).resolve()

# 親切チェック（推奨）
if not DATA_DIR.exists():
    raise FileNotFoundError(f"DATA_DIR not found: {DATA_DIR}")


# ============================================================
# ログ設定（stdout + ファイル）run.log を作る
# ============================================================
log_path = Path(ARGS.log).resolve() if ARGS.log else (OUT_RUN_DIR / "run.log") #CLI引数があればそこに保存、なければoutputに保存
log_path.parent.mkdir(parents=True, exist_ok=True) #フォルダがなければ作る

#logを初期化
logger = logging.getLogger("kasuga_gym")
logger.setLevel(logging.INFO)
logger.handlers.clear()

#ログの表示形式設定
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

#ターミナルに出力
_sh = logging.StreamHandler()
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

#ファイルに保存
_fh = logging.FileHandler(log_path, encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

#使った実行条件のログを保存
logger.info("CONFIG_PATH=%s", CONFIG_PATH)
logger.info("OUT_RUN_DIR=%s", OUT_RUN_DIR)
logger.info("NO_GANTT=%s", NO_GANTT)

# ============================================================
# matplotlib は必要なときだけ読み込む（--no-gantt なら不要）
# ============================================================
if not NO_GANTT:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    mpl.rcParams["font.family"] = "Noto Sans CJK JP" #フォントを"Noto Sans CJK JP"に固定
    mpl.rcParams["axes.unicode_minus"] = False  #-（マイナス）の文字化け防止
else:
    plt = None  # type: ignore


# ============================================================
# 日付
# ============================================================
_, last_day = calendar.monthrange(YEAR, MONTH) #月の最終日を決定
days = [date(YEAR, MONTH, d) for d in range(1, last_day + 1)] #年月日データの作成

def tm(s): #時間データを分に変換（時間＊６０＋分）
    h, m = map(int, s.split(":"))
    return h * 60 + m

def tstr(t): #分データを時間に変換（分/60の商：分/60の余り）
    return f"{t//60:02d}:{t%60:02d}"

# ============================================================
# 希望日
# ============================================================
PREF_PATH  = DATA_DIR / "preferences.json"

if not PREF_PATH.exists():
    raise FileNotFoundError(f"preferences.json not found: {PREF_PATH}")

with open(PREF_PATH, encoding="utf-8") as f: #希望日データ読み込み
    pref_raw = json.load(f)


pref_days = { #文字列をデータに変換
    team: set(date.fromisoformat(d) for d in ds)
    for team, ds in pref_raw.items()
}

# ============================================================
# イベント
# ============================================================
EVENT_PATH = DATA_DIR / "events.json"

if not EVENT_PATH.exists():
    raise FileNotFoundError(f"events.json not found: {EVENT_PATH}")

with open(EVENT_PATH, encoding="utf-8") as f: #イベントデータ読み込み
    events_raw = json.load(f)

EVENT_SLOTS = []
for ev in events_raw:
    d = date.fromisoformat(ev["date"])        #日付設定
    s = tm(ev["start"])                       #開始時間確定
    e = s + ev["duration_hours"] * 60         #終了時間確定(duration_hours=4よりイベントを4時間と指定)
    EVENT_SLOTS.append((ev["team"], d, s, e)) #イベントデータとして保存

teams = sorted(set(pref_days.keys()) | set(ev["team"] for ev in events_raw)) #対象チームを読み込み
print("対象団体:", teams)                                                 #対象チーム表示


# スナップショット保存（証跡）
save_run_snapshot(
    out_run_dir=OUT_RUN_DIR,
    config_path=CONFIG_PATH,
    pref_path=PREF_PATH,
    event_path=EVENT_PATH
)

# ============================================================
# ★公平性に使う「希望できる日数」
# ============================================================
pref_count = {}
for t in teams:
    pref_set = pref_days.get(t, set())
    pref_count[t] = len([d for d in pref_set if d in days])

print("\n=== 希望日数 ===")
for t in teams:
    print(t, pref_count[t])


# ============================================================
# 時間帯区分
# ============================================================
def is_morning(t): return 510 <= t < 660  #朝の定義（８：３０～１１：００）
def is_daytime(t): return 660 <= t < 900  #昼の定義（１１：００～１５：００）
def is_evening(t): return 900 <= t < 1080 #夕方の定義（１５：００～１８：００）
def is_night(t):   return 1080 <= t < 1260#夜の定義（１８：００～２１：００）

#朝のペナルティ
def morning_penalty(t):
    if not is_morning(t): return 0 #朝以外ペナルティなし
    if t < 570: return 7           #ペナルティ７（８：３０～９：３０）
    if t < 600: return 4           #ペナルティ４（９：３０～１０：００）
    return 2                       #ペナルティ２（１０：００～１１：００）

# ============================================================
# 使用可能時間（あなたの設定）
# ============================================================
availability_raw = config["availability"]

# YAMLのキーは文字列になりやすいので int に変換する
availability = {int(k): v for k, v in availability_raw.items()}

for day in range(1, last_day + 1):
    if day not in availability:
        raise ValueError(f"config.yaml の availability に {day} 日がありません")

def has_min_consecutive_block(slots, MIN_SLOTS, slot): #利用可能時間が最低スロット数（３）ない日を削除
    if len(slots) < MIN_SLOTS:
        return False
    sset = set(slots)
    for s in slots:
        if all((s + k*slot) in sset for k in range(MIN_SLOTS)):
            return True
    return False

# ★ 利用不可にした日（MIN_SLOTS連続が作れない日）をためる
unusable_days_by_minblock = []

def build_slots(d):     #利用可能時間を取り出す
    st, en, rs, re = availability[d.day] #(st:開始時間、en:終了時間、rs:制限開始時間、re:制限開始時間)
    if st is None:     #体育館を使えない日は空のリスト
        return []

    slots = list(range(tm(st), tm(en), slot)) #利用可能時間をスロット化（開始時間、終了時間、slot=30）

    if rs and re:       #使えない時間帯の除外
        rs_m, re_m = tm(rs), tm(re)
        slots = [t for t in slots if not (rs_m <= t < re_m)] #利用禁止時間以外をスロット化

    # ★ ここが追加：MIN_SLOTS連続が作れない日は「利用不可」にする
    if not has_min_consecutive_block(slots, MIN_SLOTS, slot):
        unusable_days_by_minblock.append(d)   # ← 日付を記録
        return []

    return slots

slots_by_day = {d: build_slots(d) for d in days} #各日付ごとに使える時間のデータ作成

def validate_inputs(pref_days, events_raw, days, slots_by_day, slot, YEAR, MONTH):
    """
    入力チェックを行い、問題があるイベントは「無かったことにして」除外する。
    また、希望日も対象月外や利用不可日を除外する（警告表示）。
    """
    valid_day_set = set(days)

    # ----------------------------
    # 希望日のバリデーション
    # ----------------------------
    cleaned_pref_days = {}
    pref_removed = []

    for team, ds in pref_days.items():
        keep = set()
        for d in ds:
            # 対象月外
            if d not in valid_day_set:
                pref_removed.append((team, d, "対象月外"))
                continue
            keep.add(d)
        cleaned_pref_days[team] = keep

    if pref_removed:
        print("\n[WARN] 希望日から除外した日付があります（入力ミス/利用不可）:")
        for team, d, reason in pref_removed:
            print(f"  - {team}: {d.isoformat()} -> 除外（{reason}）")

    # ----------------------------
    # イベントのバリデーション
    # ----------------------------
    valid_event_slots = []
    skipped = []

    for i, ev in enumerate(events_raw, start=1):
        # 必須キー
        for k in ["team", "date", "start", "duration_hours"]:
            if k not in ev:
                skipped.append((i, ev.get("team", "?"), ev.get("date", "?"), ev.get("start", "?"),
                               ev.get("duration_hours", "?"), f"必須キー {k} がありません"))
                break
        else:
            team = str(ev["team"])
            try:
                d = date.fromisoformat(ev["date"])
            except Exception:
                skipped.append((i, team, ev.get("date"), ev.get("start"), ev.get("duration_hours"),
                                "date が ISO形式(YYYY-MM-DD)ではありません"))
                continue

            # 対象月外
            if d not in valid_day_set:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "対象月外のイベント"))
                continue

            # その日が利用不可（スロットが空）
            if not slots_by_day.get(d):
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "その日は利用可能スロットがありません"))
                continue

            # 時刻と長さ
            try:
                s = tm(ev["start"])
            except Exception:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "start が HH:MM 形式ではありません"))
                continue

            try:
                dur_h = float(ev["duration_hours"])
            except Exception:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "duration_hours が数値ではありません"))
                continue

            if dur_h <= 0:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "duration_hours が 0 以下です"))
                continue

            e = s + int(dur_h * 60)

            # スロット境界に揃ってないと range(s,e,slot) が危険
            if (s % slot) != 0 or (e % slot) != 0:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                f"スロット境界に揃っていません（slot={slot}分）"))
                continue

            # 実際にその日のスロットとして存在するか（営業時間外/制限時間帯にかかると欠ける）
            day_slots_set = set(slots_by_day[d])
            missing = [t for t in range(s, e, slot) if t not in day_slots_set]
            if missing:
                skipped.append((i, team, d.isoformat(), ev.get("start"), ev.get("duration_hours"),
                                "営業時間外または制限時間帯にかかっています（利用不可スロットあり）"))
                continue

            # OK
            valid_event_slots.append((team, d, s, e))

    if skipped:
        print("\n[WARN] 実行できないイベントを除外しました（無かったことにして続行）:")
        for (i, team, d, st, dur, reason) in skipped:
            print(f"  - #{i} {team} のイベント({d} {st}, {dur}h) -> 除外（{reason}）")

    return cleaned_pref_days, valid_event_slots

# ============================================================
# 入力バリデーション（NGイベントは除外して続行）
# ============================================================
pref_days, EVENT_SLOTS = validate_inputs(
    pref_days=pref_days,
    events_raw=events_raw,
    days=days,
    slots_by_day=slots_by_day,
    slot=slot,
    YEAR=YEAR,
    MONTH=MONTH
)

# teams / イベント日集合は「除外後のEVENT_SLOTS」から作る
teams = sorted(set(pref_days.keys()) | set(team for team, _, _, _ in EVENT_SLOTS))
print("対象団体:", teams)

event_days_by_team = {(team, d) for team, d, _, _ in EVENT_SLOTS}   #イベント日と団体名のデータを作成
event_calendar_days = {d for _, d, _, _ in EVENT_SLOTS}             #イベント日のデータを作成

# ============================================================
# ★ 利用不可にした日付を出力
# ============================================================
print("\n=== MIN_SLOTS連続が作れず「利用不可」にした日 ===")
if unusable_days_by_minblock:
    for d in unusable_days_by_minblock:
        print(d.isoformat())
else:
    print("(該当なし)")

# ============================================================
# ★イベントが「その日の全スロット」を覆う日を検出（null扱いにする）
# ============================================================
full_event_days = set()

for d in event_calendar_days:
    day_slots = set(slots_by_day.get(d, []))
    if not day_slots:
        continue

    covered = set()
    for team, dd, s, e in EVENT_SLOTS:
        if dd != d:
            continue
        covered.update(range(s, e, slot))

    # day_slots が全部 covered に含まれる → その日はイベント専用（他団体は実質使えない）
    if day_slots.issubset(covered):
        full_event_days.add(d)

if full_event_days:
    print("\n[INFO] イベントが全枠を覆うため null 扱い（非イベント配分対象外）にする日:")
    for d in sorted(full_event_days):
        print(" ", d.isoformat())

# ============================================================
# CP-SAT モデル
# ============================================================
model = cp_model.CpModel() #CP-SATモデルの作成

# x[team, day, time]
x = {}
for d in days:
    for t in slots_by_day[d]:
        for team in teams:
            x[(team, d, t)] = model.NewBoolVar(f"x_{team}_{d}_{t}")  #ある日のある時間にある団体が使うかを０：使わない、１：使うで定義


# ============================================================
# イベント確定割当（最優先）
# ============================================================
for team, d, s, e in EVENT_SLOTS:
    for t in range(s, e, slot):
        model.Add(x[(team, d, t)] == 1)      #イベントデータに入っているデータをモデルに追加
        for o in teams:
            if o != team:                    #イベントをするチームでないならば
                model.Add(x[(o, d, t)] == 0) #イベントの時間はほかのチームは絶対使えない（イベントの優先確保）
    for t in slots_by_day[d]:                #イベントする団体はその日の利用はそれだけ
        if t < s or t >= e:
            model.Add(x[(team,d,t)] == 0)
# ============================================================
# 希望日制約（イベント日は例外）
# 👉 希望している団体のみで分配
# ============================================================
for d in days:
    for team in teams:
        if (team, d) in event_days_by_team:     #その日にイベントをする団体はスキップ
            continue
        if d not in pref_days.get(team, set()): #希望日にしていない日は一日中使えない
            for t in slots_by_day[d]:
                model.Add(x[(team, d, t)] == 0)

# ============================================================
# 各スロットは必ず1団体（方法A：enumerateで高速化）
# ============================================================
for d in days:
    slots = slots_by_day[d]
    n = len(slots)
    if n == 0:
        continue

    for i, t in enumerate(slots):
        # ここで「t から MIN_SLOTS 連続で取れるか」を判定（can_start_minimum と同じ判定）
        ok = True
        for k in range(1, MIN_SLOTS):
            if i + k >= n:
                ok = False
                break
            if slots[i + k] != t + k * slot:
                ok = False
                break

        if ok:
            # 連続 MIN_SLOTS が作れる開始点は必ず1団体
            model.Add(sum(x[(team, d, t)] for team in teams) == 1)
        else:
            # 作れない開始点は空でもOK
            model.Add(sum(x[(team, d, t)] for team in teams) <= 1)

# ============================================================
# 使用量 U と 使用有無 y
# ============================================================
U, y = {}, {}
for d in days:
    T = len(slots_by_day[d])
    for team in teams:
        U[(team, d)] = model.NewIntVar(0, T, f"U_{team}_{d}") #ある日のある時間にある団体が使用するスロット数を算出
        y[(team, d)] = model.NewBoolVar(f"y_{team}_{d}")  #ある日のある時間にある団体の使用の有無（０：使わない、１：使う）
        model.Add(U[(team, d)] == sum(x[(team, d, t)] for t in slots_by_day[d])) #その日の利用時間は割り当てられた30分スロットの合計
        model.Add(U[(team, d)] >= MIN_SLOTS).OnlyEnforceIf(y[(team, d)]) #使う時間は最低利用時間を満たす
        model.Add(U[(team, d)] == 0).OnlyEnforceIf(y[(team, d)].Not()) #使わないなら利用時間は０

# ============================================================
# 1日1回・連続 ＋ 開始時刻 start_time
# ============================================================
start_time = {}

for team in teams:
    for d in days:
        ts = slots_by_day[d]
        if not ts:  #もしその日に使わないならスキップ
            continue

        starts = []
        for i, t in enumerate(ts):
            s = model.NewBoolVar(f"s_{team}_{d}_{t}") #開始時間を決める
            prev = x[(team, d, ts[i-1])] if i > 0 else None #直前に使っているか
            cur = x[(team, d, t)] #現在使っているか

            if prev is None:
                model.Add(s == cur)
            else:
                model.Add(s >= cur - prev)
                model.Add(s <= cur)
                model.Add(s <= 1 - prev)

            starts.append(s)

        model.Add(sum(starts) <= 1) #複数回使い始めることは禁止

        st = model.NewIntVar(0, 24*60, f"start_{team}_{d}")
        start_time[(team, d)] = st

        model.Add(st == sum(t * s for t, s in zip(ts, starts)))
        model.Add(st == 0).OnlyEnforceIf(y[(team, d)].Not())

# ============================================================
# ★日内公平性（開始順制限つき）
# ・同じ日に使う団体同士の差 ≤ 30分
# ・早く始まる団体ほど利用時間は短い
# ・イベント日は除外
# ============================================================
TIE = 1  # 30分

for d in days:
    if d in event_calendar_days: #イベント日はスキップ
        continue

    ts = slots_by_day[d] #使用できない日はスキップ
    if not ts:
        continue

    for i in range(len(teams)): #同じ日に使う2団体について行う
        for j in range(i + 1, len(teams)):
            a = teams[i]
            b = teams[j]

            both = model.NewBoolVar(f"both_{a}_{b}_{d}") #その日に2団体とも使うことを表す（1：どちらも利用、０：それ以外）
            model.AddBoolAnd([y[(a, d)], y[(b, d)]]).OnlyEnforceIf(both)
            model.AddBoolOr(
                [y[(a, d)].Not(), y[(b, d)].Not()]
            ).OnlyEnforceIf(both.Not())

            # 利用時間差 ≤ 30分（上下両方から）
            model.Add(U[(a, d)] - U[(b, d)] <= TIE).OnlyEnforceIf(both)
            model.Add(U[(b, d)] - U[(a, d)] <= TIE).OnlyEnforceIf(both)

            # 開始順制約
            a_before_b = model.NewBoolVar(f"ab_{a}_{b}_{d}") #先に使う団体(0:B、1:A）
            model.Add(start_time[(a, d)] <= start_time[(b, d)]).OnlyEnforceIf([both, a_before_b])
            model.Add(start_time[(b, d)] <= start_time[(a, d)]).OnlyEnforceIf([both, a_before_b.Not()])
            #先に使う方が時間が短い
            model.Add(U[(a, d)] <= U[(b, d)]).OnlyEnforceIf([both, a_before_b])
            model.Add(U[(b, d)] <= U[(a, d)]).OnlyEnforceIf([both, a_before_b.Not()])


# ============================================================
# イベント日の時の日内公平性
# ・イベント実施団体は除外
# ・その日を希望している「非イベント団体」のみで日内公平性を適用
# ============================================================
for d in days:
    if d not in event_calendar_days:  # イベント日でなければスキップ
        continue
    if d in full_event_days:
        continue

    ts = slots_by_day[d]
    if not ts:
        continue

    # --- ① その日にイベントを行う団体 ---
    event_teams_today = {
        team for team, dd, _, _ in EVENT_SLOTS if dd == d
    }

    # --- ② イベント以外で、その日を希望している団体 ---
    non_event_pref_teams = [
        t for t in teams
        if t not in event_teams_today and d in pref_days.get(t, set())
    ]

    # 2団体未満なら公平性制約は不要
    if len(non_event_pref_teams) < 2:
        continue

    # --- ③ 日内公平性（通常日と同じ制約） ---
    for i in range(len(non_event_pref_teams)):
        for j in range(i + 1, len(non_event_pref_teams)):
            a = non_event_pref_teams[i]
            b = non_event_pref_teams[j]

            both = model.NewBoolVar(f"both_ev_{a}_{b}_{d}")

            model.AddBoolAnd([y[(a, d)], y[(b, d)]]).OnlyEnforceIf(both)
            model.AddBoolOr(
                [y[(a, d)].Not(), y[(b, d)].Not()]
            ).OnlyEnforceIf(both.Not())

            # 利用時間差 ≤ 30分
            model.Add(U[(a, d)] - U[(b, d)] <= TIE).OnlyEnforceIf(both)
            model.Add(U[(b, d)] - U[(a, d)] <= TIE).OnlyEnforceIf(both)

            # 開始順制約
            a_before_b = model.NewBoolVar(f"ab_ev_{a}_{b}_{d}")

            model.Add(
                start_time[(a, d)] <= start_time[(b, d)]
            ).OnlyEnforceIf([both, a_before_b])

            model.Add(
                start_time[(b, d)] <= start_time[(a, d)]
            ).OnlyEnforceIf([both, a_before_b.Not()])

            # 先に使う方が利用時間は短い
            model.Add(U[(a, d)] <= U[(b, d)]).OnlyEnforceIf([both, a_before_b])
            model.Add(U[(b, d)] <= U[(a, d)]).OnlyEnforceIf([both, a_before_b.Not()])

        


        

# ============================================================
# 時間帯別 月合計
# ============================================================
zone_counts = {z: {} for z in ["morning", "daytime", "evening", "night"]} #時間帯ごとに入れる辞書

for team in teams:
    for z in zone_counts:
        zone_counts[z][team] = model.NewIntVar(0, 2000, f"{z}_{team}") #時間帯ごとにその団体が使ったスロット数を記録

    model.Add(zone_counts["morning"][team] ==
              sum(x[(team, d, t)] for d in days for t in slots_by_day[d] if is_morning(t))) #朝の利用量の合計を算出
    model.Add(zone_counts["daytime"][team] ==
              sum(x[(team, d, t)] for d in days for t in slots_by_day[d] if is_daytime(t))) #昼の利用量の合計を算出
    model.Add(zone_counts["evening"][team] ==
              sum(x[(team, d, t)] for d in days for t in slots_by_day[d] if is_evening(t))) #夕方の利用量の合計を算出
    model.Add(zone_counts["night"][team] ==
              sum(x[(team, d, t)] for d in days for t in slots_by_day[d] if is_night(t)))   #夜の利用量の合計を算出

# ============================================================
# 月合計 totalM（イベント日も含める）
# ============================================================
totalM = {}
for team in teams:
    totalM[team] = model.NewIntVar(0, 2000, f"totalM_{team}")
    model.Add(totalM[team] == sum(U[(team, d)] for d in days)) #月に使ったスロット数の合計を算出

# ============================================================
# 目的関数
# ============================================================
obj = []

# (1) 使用団体数最大化
for d in days:
    obj.append(TEAM_W * sum(y[(team, d)] for team in teams)) #使用団体1団体につき10000の重み付け

# (2) 日内公平性（イベント日除外）※使った団体(y=1)だけで max-min
# 利用時間差が30分以内はハード制約として入れているため、ここでは利用時間に空きがあるなら利用時間を増やすという制約をソフトに＋条件としている
for d in days:
    if d in event_calendar_days:
        continue
    
    ts = slots_by_day[d]
    T = len(ts)
    if T == 0:
        continue

    # その日に使った団体数 used_cnt
    used_cnt = model.NewIntVar(0, len(teams), f"usedCnt_{d}")
    model.Add(used_cnt == sum(y[(t, d)] for t in teams))

    active = model.NewBoolVar(f"active_daily_{d}")  # 2団体以上なら評価
    model.Add(used_cnt >= 2).OnlyEnforceIf(active)
    model.Add(used_cnt <= 1).OnlyEnforceIf(active.Not())

    # max/min を「使ってない団体は除外」して作る
    maxU = model.NewIntVar(0, T, f"maxU_used_{d}") #最長利用時間の団体のスロット数
    minU = model.NewIntVar(0, T, f"minU_used_{d}") #最小利用時間の団体のスロット数

    max_terms = []
    min_terms = []

    for t in teams:
        # max側：使ってないなら 0、使ったら U
        mU = model.NewIntVar(0, T, f"mU_{t}_{d}")
        model.Add(mU == U[(t, d)]).OnlyEnforceIf(y[(t, d)])
        model.Add(mU == 0).OnlyEnforceIf(y[(t, d)].Not())
        max_terms.append(mU)

        # min側：使ったら U、使ってないなら T（大きい値）にして min から除外
        nU = model.NewIntVar(0, T, f"nU_{t}_{d}")
        model.Add(nU == U[(t, d)]).OnlyEnforceIf(y[(t, d)])
        model.Add(nU == T).OnlyEnforceIf(y[(t, d)].Not())
        min_terms.append(nU)

    model.AddMaxEquality(maxU, max_terms)
    model.AddMinEquality(minU, min_terms)

    spread = model.NewIntVar(0, T, f"spread_used_{d}")
    model.Add(spread == maxU - minU)

    # 2団体未満の日は spread=0 にして無評価
    model.Add(spread == 0).OnlyEnforceIf(active.Not())

    obj.append(DAILY_SPREAD_W * spread)


# (2') 日内公平性（イベント日：非イベント希望団体のみ）※使った団体(y=1)だけで max-min
for d in days:
    if d not in event_calendar_days:
        continue
    if d in full_event_days:
        continue
    ts = slots_by_day[d]
    T = len(ts)
    if T == 0:
        continue

    event_teams_today = {team for team, dd, _, _ in EVENT_SLOTS if dd == d}

    non_event_pref_teams = [
        t for t in teams
        if t not in event_teams_today and d in pref_days.get(t, set())
    ]

    if len(non_event_pref_teams) < 2:
        continue

    # その日の「非イベント希望団体」のうち使った団体数
    used_cnt = model.NewIntVar(0, len(non_event_pref_teams), f"usedCnt_ev_{d}")
    model.Add(used_cnt == sum(y[(t, d)] for t in non_event_pref_teams))

    active = model.NewBoolVar(f"active_ev_{d}")  # 2団体以上なら評価
    model.Add(used_cnt >= 2).OnlyEnforceIf(active)
    model.Add(used_cnt <= 1).OnlyEnforceIf(active.Not())

    maxU_ev = model.NewIntVar(0, T, f"maxU_nonEvent_used_{d}")
    minU_ev = model.NewIntVar(0, T, f"minU_nonEvent_used_{d}")

    max_terms = []
    min_terms = []

    for t in non_event_pref_teams:
        # max側：使ってないなら 0、使ったら U
        mU = model.NewIntVar(0, T, f"mU_ev_{t}_{d}")
        model.Add(mU == U[(t, d)]).OnlyEnforceIf(y[(t, d)])
        model.Add(mU == 0).OnlyEnforceIf(y[(t, d)].Not())
        max_terms.append(mU)

        # min側：使ったら U、使ってないなら T にして min から除外
        nU = model.NewIntVar(0, T, f"nU_ev_{t}_{d}")
        model.Add(nU == U[(t, d)]).OnlyEnforceIf(y[(t, d)])
        model.Add(nU == T).OnlyEnforceIf(y[(t, d)].Not())
        min_terms.append(nU)

    model.AddMaxEquality(maxU_ev, max_terms)
    model.AddMinEquality(minU_ev, min_terms)

    spread_ev = model.NewIntVar(0, T, f"spread_ev_used_{d}")
    model.Add(spread_ev == maxU_ev - minU_ev)

    # 2団体未満なら無評価
    model.Add(spread_ev == 0).OnlyEnforceIf(active.Not())

    obj.append(DAILY_SPREAD_EV_W * spread_ev)


# ============================================================
# (3) ★月合計公平性（希望日数比率で公平化：全団体）
#     目標: totalM[a] : totalM[b] ≈ pref_count[a] : pref_count[b]
#     → |totalM[a]*pref[b] - totalM[b]*pref[a]| を小さくする
# ============================================================


prop_teams = [t for t in teams if pref_count.get(t, 0) > 0]  # 分母0は除外

for i in range(len(prop_teams)):
    for j in range(i + 1, len(prop_teams)):
        a = prop_teams[i] #aチーム
        b = prop_teams[j] #bチーム
        wa = pref_count[a] #aの希望日数
        wb = pref_count[b] #bの希望日数

        # expr = totalM[a]*wb - totalM[b]*wa （totalM[a]はaの月合計利用時間）
        expr = totalM[a] * wb - totalM[b] * wa

        # |expr| を表す diff
        diff = model.NewIntVar(0, 2000 * max(wa, wb), f"diff_totalM_{a}_{b}")
        model.Add(expr <= diff)
        model.Add(-expr <= diff)

        obj.append(-PROP_MONTH_W * diff)

# ============================================================
# (4)：朝負担の「団体間の偏り」を抑える（max-min を小さくする）
# ============================================================

# 各団体の「朝負担スコア」 morning_burden[team] を作る
morning_burden = {}

# 上界（とりあえず安全に大きめに見積もる）
# penalty 最大7、1スロット=30分、日数 last_day、1日に朝スロット最大5（8:30-11:00=5スロット）
MORN_BURDEN_UB = 7 * 5 * last_day  # 例：7*5*31=1085

for team in teams:
    morning_burden[team] = model.NewIntVar(0, MORN_BURDEN_UB, f"morning_burden_{team}")

    # 朝スロットだけ拾って「負担=penalty×割当」を全部足す
    model.Add(
        morning_burden[team] ==
        sum(
            morning_penalty(t) * x[(team, d, t)]
            for d in days
            for t in slots_by_day[d]
            if morning_penalty(t) > 0   # 朝以外(0)は含めない
        )
    )

maxB = model.NewIntVar(0, MORN_BURDEN_UB, "max_morning_burden") #朝負担が一番大きい団体
minB = model.NewIntVar(0, MORN_BURDEN_UB, "min_morning_burden") #朝負担が一番小さい団体

model.AddMaxEquality(maxB, [morning_burden[t] for t in teams])
model.AddMinEquality(minB, [morning_burden[t] for t in teams])

obj.append(-MORN_SPREAD_W * (maxB - minB))

# ============================================================
# (5) ★時間帯別公平性（希望日数比率で公平化：全団体）
# ============================================================


for z in zone_counts:
    for i in range(len(prop_teams)):
        for j in range(i + 1, len(prop_teams)):
            a = prop_teams[i]
            b = prop_teams[j]
            wa = pref_count[a]
            wb = pref_count[b]

            expr = zone_counts[z][a] * wb - zone_counts[z][b] * wa

            diff = model.NewIntVar(0, 2000 * max(wa, wb), f"diff_{z}_{a}_{b}")
            model.Add(expr <= diff)
            model.Add(-expr <= diff)

            obj.append(-PROP_ZONE_W * diff)

# ============================================================
# (6) 空き時間ペナルティ（利用可能時間内の未割当スロットを減らす）
# ============================================================
for d in days:
    ts = slots_by_day[d]
    if not ts:
        continue

    for t in ts:
        # そのスロットに割り当てられている団体数（0 or 1 の想定）
        assigned = sum(x[(team, d, t)] for team in teams)

        # 未割当なら 1、割当済なら 0 になる（線形式）
        # ※ assigned は 0/1 なので 1-assigned でOK
        obj.append(-IDLE_W * (1 - assigned))


model.Maximize(sum(obj)) #objの和を最大化する



# ============================================================
# Solve
# ============================================================
solver = cp_model.CpSolver() #CP-SAT起動
solver.parameters.max_time_in_seconds = MAX_SOLVE_SECONDS #計算に使う時間の指定（60秒）
status = solver.Solve(model) #問題を解く（実行）
logger.info("status=%s", solver.StatusName(status))
print("status:", solver.StatusName(status)) #解の表示（OPTIMAL:最適解発見,FEASIBLE:最適とは限らないが解あり,INFEASIBLE:制約が厳しくて解なし,UNKNOWN:時間切れ等で不明）

if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    raise RuntimeError("解が見つかりませんでした（制約が厳しすぎる可能性）")

# ============================================================
# 目的関数の内訳を集計して表示（使った団体だけ版）
# ※ Solve() 後にコピペ
# ============================================================
def compute_objective_breakdown_used_only():
    # ----------------------------
    # (1) 使用団体数最大化
    # ----------------------------
    used_team_count = 0
    for d in days:
        for team in teams:
            if solver.Value(y[(team, d)]) == 1:
                used_team_count += 1
    used_team_score = TEAM_W * used_team_count

    # ----------------------------
    # (2) 日内公平性（イベント日除外）
    #     「その日に使った団体(y=1)だけ」で maxU-minU
    # ----------------------------
    daily_spread_sum = 0
    daily_spread_score = 0
    daily_days = 0
    daily_used_pairs_days = 0  # 2団体以上使った日

    for d in days:
        if d in event_calendar_days:
            continue
        ts = slots_by_day[d]
        if not ts:
            continue

        used_today = [t for t in teams if solver.Value(y[(t, d)]) == 1]
        if len(used_today) < 2:
            # 0 or 1団体しか使ってない日は「差」が定義しにくいので集計しない
            continue

        us = [solver.Value(U[(t, d)]) for t in used_today]
        spread = max(us) - min(us)

        daily_days += 1
        daily_used_pairs_days += 1
        daily_spread_sum += spread
        daily_spread_score += DAILY_SPREAD_W * spread

    # ----------------------------
    # (2') 日内公平性（イベント日：非イベント希望団体のみ / ソフト）
    #     「非イベント希望」かつ「その日に使った団体(y=1)だけ」で maxU-minU
    # ----------------------------
    event_spread_sum = 0
    event_spread_score = 0
    event_days = 0

    for d in days:
        if d not in event_calendar_days:
            continue
        ts = slots_by_day[d]
        if not ts:
            continue

        event_teams_today = {team for team, dd, _, _ in EVENT_SLOTS if dd == d}
        non_event_pref_teams = [
            t for t in teams
            if t not in event_teams_today and d in pref_days.get(t, set())
        ]

        used_non_event = [
            t for t in non_event_pref_teams
            if solver.Value(y[(t, d)]) == 1
        ]

        if len(used_non_event) < 2:
            continue

        us = [solver.Value(U[(t, d)]) for t in used_non_event]
        spread = max(us) - min(us)

        event_days += 1
        event_spread_sum += spread
        event_spread_score += DAILY_SPREAD_EV_W * spread

    # ----------------------------
    # (3) 月合計比率公平性（全団体ペア）
    #     -PROP_MONTH_W * |totalM[a]*wb - totalM[b]*wa|
    # ----------------------------
    totalM_val = {t: sum(solver.Value(U[(t, d)]) for d in days) for t in teams}
    prop_teams = [t for t in teams if pref_count.get(t, 0) > 0]

    month_pairs = 0
    month_diff_sum = 0
    month_score = 0

    for i in range(len(prop_teams)):
        for j in range(i + 1, len(prop_teams)):
            a = prop_teams[i]
            b = prop_teams[j]
            wa = pref_count[a]
            wb = pref_count[b]

            diff = abs(totalM_val[a] * wb - totalM_val[b] * wa)
            month_pairs += 1
            month_diff_sum += diff
            month_score += -PROP_MONTH_W * diff

    # ----------------------------
    # (4) 朝ペナルティ
    #     -EARLY_MORNING_W * p * x
    # ----------------------------


    # morning_penalty(t) はすでに定義済み前提
    morning_burden_val = {}
    for team in teams:
        s = 0
        for d in days:
            for t in slots_by_day[d]:
                p = morning_penalty(t)
                if p > 0 and solver.Value(x[(team, d, t)]) == 1:
                    s += p
        morning_burden_val[team] = s

    maxB_val = max(morning_burden_val.values()) if teams else 0
    minB_val = min(morning_burden_val.values()) if teams else 0
    morning_score = -MORN_SPREAD_W * (maxB_val - minB_val)

    # 朝負担 上位表示（上位3団体）
    top_morning = sorted(morning_burden_val.items(), key=lambda kv: kv[1], reverse=True)[:3]

    # ----------------------------
    # (5) 時間帯比率公平性（全団体ペア×4）
    #     -PROP_ZONE_W * |zone[a]*wb - zone[b]*wa|
    # ----------------------------
    zones = {
        "morning":  lambda t: 510 <= t < 660,
        "daytime":  lambda t: 660 <= t < 900,
        "evening":  lambda t: 900 <= t < 1080,
        "night":    lambda t: 1080 <= t < 1260,
    }

    zone_val = {z: {team: 0 for team in teams} for z in zones}
    for d in days:
        for t in slots_by_day[d]:
            for team in teams:
                if solver.Value(x[(team, d, t)]) == 1:
                    for z, pred in zones.items():
                        if pred(t):
                            zone_val[z][team] += 1

    zone_pairs = len(prop_teams) * (len(prop_teams) - 1) // 2
    zone_diff_sum = {z: 0 for z in zones}
    zone_score = 0

    for z in zones:
        for i in range(len(prop_teams)):
            for j in range(i + 1, len(prop_teams)):
                a = prop_teams[i]
                b = prop_teams[j]
                wa = pref_count[a]
                wb = pref_count[b]

                diff = abs(zone_val[z][a] * wb - zone_val[z][b] * wa)
                zone_diff_sum[z] += diff
                zone_score += -PROP_ZONE_W * diff
    # ----------------------------
    # (6) 空き時間ペナルティ
    #     -IDLE_W * (未割当スロット数)
    # ----------------------------
    idle_slots = 0
    idle_score = 0

    for d in days:
        ts = slots_by_day[d]
        if not ts:
            continue

        for t in ts:
            assigned = sum(solver.Value(x[(team, d, t)]) for team in teams)
            if assigned == 0:
                idle_slots += 1
                idle_score += -IDLE_W


    # ----------------------------
    # 合計（あなたの現目的関数に合わせて PREF_BONUS は含めない）
    # ----------------------------
    total = (
        used_team_score
        + daily_spread_score
        + event_spread_score
        + month_score
        + morning_score
        + zone_score
        + idle_score        
    )


        # ----------------------------
    # 表示（＋画像保存用に lines へも保存）
    # ----------------------------
    lines = []
    lines.append("================ Objective Breakdown (used-only) ================")
    lines.append(f"(1) Use teams:        score={used_team_score:,}  (count y=1: {used_team_count})  weight(TEAM_W)={TEAM_W}")
    lines.append(f"(2) Daily spread:     score={daily_spread_score:,}  (days={daily_used_pairs_days}, sum max-min={daily_spread_sum}) weight={DAILY_SPREAD_W}  [used teams only]")
    lines.append(f"(2') Event spread:    score={event_spread_score:,}  (days={event_days}, sum max-min={event_spread_sum}) weight={DAILY_SPREAD_EV_W}  [used teams only]")
    lines.append(f"(3) Month ratio:      score={month_score:,}  (pairs={month_pairs}, sum diff={month_diff_sum:,}) weight={PROP_MONTH_W}")
    lines.append(f"(4) Morning fairness  score={morning_score:,}  (maxB-minB={maxB_val - minB_val}, maxB={maxB_val}, minB={minB_val}) weight(MORN_SPREAD_W)={MORN_SPREAD_W}")
    if top_morning:
        lines.append("     top morning burden: " + ", ".join([f"{t}={v}" for t, v in top_morning]))
    lines.append(f"(5) Zone ratio:       score={zone_score:,}  (pairs={zone_pairs} per zone) weight={PROP_ZONE_W}")
    lines.append(f"(6) Idle slots:       score={idle_score:,}  (idle slots={idle_slots}) weight={IDLE_W}")
    for z in ["morning", "daytime", "evening", "night"]:
        lines.append(f"    - zone {z}: sum diff={zone_diff_sum[z]:,}")
    lines.append("-----------------------------------------------------")
    lines.append(f"TOTAL objective (approx from breakdown) = {total:,}")
    lines.append("==================================================================")

    # コンソールに出す
    print("\n" + "\n".join(lines) + "\n")

    # 画像保存（output/YYYY-MM/ に保存）
    out_png = OUT_RUN_DIR / f"objective_breakdown_used_only_{RUN_TAG}.png"
    out_pdf = OUT_RUN_DIR / f"objective_breakdown_used_only_{RUN_TAG}.pdf"
    save_text_image(lines, out_png, out_pdf, title="Objective Breakdown (used-only)")
    if not NO_GANTT:
        print(f"[保存完了] {out_png}")
        print(f"[保存完了] {out_pdf}")

# ============================================================
# 画像保存：テキスト（Objective Breakdown）
# ============================================================
def save_text_image(lines: list[str], out_png: Path, out_pdf: Path, title: str = ""):
    if NO_GANTT:
        return
    if plt is None:
        return

    # 行数に応じて高さを調整（A4以上）
    n = len(lines)
    fig_w = 8.27  # A4 width
    fig_h = max(11.69, 0.28 * n)  # 行数で伸びる（転記用リストと同じ思想）

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    y = 0.98
    dy = 0.98 / max(n, 1)

    for s in lines:
        if s.startswith("====") or s.startswith("----"):
            ax.text(0.03, y, s, va="top", ha="left", fontsize=10, color="#222222")
        elif s.startswith("("):
            ax.text(0.03, y, s, va="top", ha="left", fontsize=11, color="#222222")
        elif s.strip() == "":
            pass
        else:
            ax.text(0.03, y, s, va="top", ha="left", fontsize=12, fontweight="bold", color="#222222")
        y -= dy

    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)

compute_objective_breakdown_used_only()

# ============================================================
# 表示オプション（... を出さない）
# ============================================================
pd.set_option("display.max_colwidth", None)
pd.set_option("display.max_rows", None)

# ============================================================
# ★希望団体0日の判定（イベント日を除外）
# ============================================================
pref_zero_days = set()
for d in days:
    if d in event_calendar_days: #イベントがあるならスキップ
        continue

    # 「希望している団体」が 1つもない日
    if not any(d in pref_days.get(t, set()) for t in teams):
        pref_zero_days.add(d)

# ============================================================
# 描画（色指定＋自動割当・完全版）
# ============================================================
from matplotlib import rcParams
import matplotlib.pyplot as plt

import matplotlib as mpl

mpl.rcParams["font.family"] = "Noto Sans CJK JP"
mpl.rcParams["axes.unicode_minus"] = False

# ============================================================
# 団体ごとの固定色（既存）
# ============================================================
TEAM_COLORS = {
    "医学フットサル同好会": "#4E79A7",
    "インドネシア学友会": "#76B7B2",
    "ULISバレーボール部": "#E15759",
    "SPIKERS'inc": "#B07AA1",
    "KickChat T-ACT": "#F28E2B",
    "中国留学生学友会": "#59A14F",
    "ULISバドミントン部": "#9C755F",
}
# ============================================================
# 曜日データ
# ============================================================
from datetime import datetime, date

JP_WD = ["月", "火", "水", "木", "金", "土", "日"]

def fmt_date_wday(d_like) -> str:
    """
    '2026-01-17' / Timestamp / date などを受けて
    '2026-01-17(土)' の形で返す
    """
    if isinstance(d_like, date) and not isinstance(d_like, datetime):
        d = d_like
    else:
        d = pd.to_datetime(d_like).date()
    return f"{d.isoformat()}({JP_WD[d.weekday()]})"

# ============================================================
# schedule.csv（Date / Blocks）
# ============================================================
rows = []

for d in days:
    ts = slots_by_day[d]

    # 希望団体0日の出力
    if d in pref_zero_days:
        rows.append({"Date": d.isoformat(), "Blocks": "希望団体0"})
        continue

    # 利用不可日の出力
    if not ts:
        rows.append({"Date": d.isoformat(), "Blocks": "(利用不可)"})
        continue

    # タイムライン復元（その時刻に割り当たった団体を拾う）
    timeline = []
    for t in ts:
        chosen = None
        for team in teams:
            if solver.Value(x[(team, d, t)]):
                chosen = team
                break
        if chosen is None:
            chosen = "(未割当)"
        timeline.append((t, chosen))

    # 連続区間にまとめる
    blocks = []
    cur_team, s, p = timeline[0][1], timeline[0][0], timeline[0][0]
    for t, team in timeline[1:]:
        if team == cur_team and t == p + slot:
            p = t
        else:
            blocks.append((cur_team, s, p + slot))
            cur_team, s, p = team, t, t
    blocks.append((cur_team, s, p + slot))

    rows.append({
        "Date": d.isoformat(),
        "Blocks": "\n".join(f"{team} {tstr(s)}-{tstr(e)}" for team, s, e in blocks)
    })

df = pd.DataFrame(rows)
df.to_csv(OUT_RUN_DIR / f"schedule_{RUN_TAG}.csv", index=False, encoding="utf-8-sig")


# ============================================================
# ① 団体別スケジュール（配布用：連続ブロック）
# schedule_by_team.csv
# ============================================================
team_rows = []

for d in days:
    ts = slots_by_day[d]
    if not ts:
        continue
    if d in pref_zero_days:
        continue

    timeline = []
    for t in ts:
        chosen = None
        for team in teams:
            if solver.Value(x[(team, d, t)]):
                chosen = team
                break
        if chosen is None:
            continue
        timeline.append((t, chosen))

    if not timeline:
        continue

    blocks = []
    cur_team, s, p = timeline[0][1], timeline[0][0], timeline[0][0]
    for t, team in timeline[1:]:
        if team == cur_team and t == p + slot:
            p = t
        else:
            blocks.append((cur_team, s, p + slot))
            cur_team, s, p = team, t, t
    blocks.append((cur_team, s, p + slot))

    for team, s, e in blocks:
        team_rows.append({
            "Team": team,
            "Date": d.isoformat(),
            "Time": f"{tstr(s)}–{tstr(e)}",
            "Hours": round((e - s) / 60, 2)
        })

schedule_by_team = pd.DataFrame(team_rows)

# ---- CSV保存（既存）----
schedule_by_team.to_csv(
    OUT_RUN_DIR / f"schedule_by_team_{RUN_TAG}.csv",
    index=False,
    encoding="utf-8-sig"
)
# ============================================================
# 提出用紙 転記用リスト（表示 + 画像保存）
# ============================================================

# 表示用（df_csv_sorted 形式）
df_csv_sorted = schedule_by_team.sort_values(
    ["Team", "Date", "Time"]
).reset_index(drop=True)




# ------------------------------------------------------------
# (1) コンソール表示（団体名だけ色：ANSI）
#   ※ Git Bash / Windows Terminal では色が出やすい
#   ※ もし色が出ない環境なら「色なし」でも動く
# ------------------------------------------------------------
def _team_color(team: str) -> str:
    return TEAM_COLORS.get(team, "#222222")

def _ansi_hex(hex_color: str) -> str:
    """#RRGGBB → ANSI 24bit escape"""
    try:
        h = hex_color.lstrip("#")
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except Exception:
        return ""

ANSI_RESET = "\033[0m"

# 画像用に「行情報」を保持する（1行ずつ描画するため）
# 例: {"kind":"header"/"line"/"sep"/"blank", "text":..., "team":...}

print("\n" + "=" * 60)
print("【提出用紙 転記用リスト】")
print("※このまま紙に書き写せます")
print("=" * 60)

draw_rows = []
draw_rows.append({"kind": "title", "text": "【提出用紙 転記用リスト】"})
draw_rows.append({"kind": "title2", "text": "※このまま紙に書き写せます"})
draw_rows.append({"kind": "sep", "text": "=" * 48})

for team, g in df_csv_sorted.groupby("Team", sort=True):
    if g.empty:
        continue

    header1 = f"■ {team}"
    header2 = f"（全{len(g)}枠）"
    # console（団体名だけ色）
    c = _ansi_hex(_team_color(team))
    print("\n■ " + c + team + ANSI_RESET)
    print(f"（全{len(g)}枠）")
    print("-" * 40)

    draw_rows.append({"kind": "blank", "text": ""})
    draw_rows.append({"kind": "header1", "team": team, "text": header1})
    draw_rows.append({"kind": "header2", "team": team, "text": header2})
    draw_rows.append({"kind": "sep2", "text": "-" * 48})

    for _, row in g.iterrows():
        date_str = fmt_date_wday(row["Date"])
        time_str = str(row["Time"])
        dur = row.get("Hours", None)

        if dur is None:
            dur_str = ""
        else:
            try:
                dur_int = int(dur) if float(dur).is_integer() else float(dur)
                dur_str = f"  ({dur_int}h)"
            except Exception:
                dur_str = f"  ({dur}h)"

        s = f"・{date_str}  {time_str}{dur_str}"
        print(s)
        draw_rows.append({"kind": "line", "text": s})

# ============================================================
# 画像保存（提出用紙 転記用リスト）
# ============================================================
if not NO_GANTT:
    out_png = OUT_RUN_DIR / f"group_schedule_{RUN_TAG}.png"
    out_pdf = OUT_RUN_DIR / f"group_schedule_{RUN_TAG}.pdf"

    # 行数に応じて高さを調整（A4以上）
    n = len(draw_rows)
    fig_w = 8.27  # A4 width
    fig_h = max(11.69, 0.26 * n)  # 行数で伸びる

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    # 上から等間隔に描画
    y = 0.98
    dy = 0.98 / max(n, 1)

    for r in draw_rows:
        kind = r["kind"]
        text = r["text"]

        if kind in ("title", "title2"):
            ax.text(0.03, y, text, va="top", ha="left", fontsize=13, fontweight="bold", color="#222222")
        elif kind == "sep":
            ax.text(0.03, y, text, va="top", ha="left", fontsize=11, color="#222222")
        elif kind == "sep2":
            ax.text(0.03, y, text, va="top", ha="left", fontsize=10, color="#222222")
        elif kind == "blank":
            # 何も書かずに行送り
            pass
        elif kind == "header1":
            team = r.get("team", "")
            # headerの中で団体名だけ色にするため、2回描画する
            # 例: "■ {team} \n（全N枠）"
            prefix = "■ "
            suffix = text.replace(f"■ {team}", "")
            ax.text(0.03, y, prefix, va="top", ha="left", fontsize=12, fontweight="bold", color="#222222")

            # 団体名
            ax.text(0.06, y, team, va="top", ha="left", fontsize=12, fontweight="bold", color=_team_color(team))
        elif kind == "header2":
            ax.text(0.06, y, r["text"], va="top", ha="left", fontsize=11, fontweight="bold", color="#222222")
        elif kind == "line":
            ax.text(0.03, y, text, va="top", ha="left", fontsize=11, color="#222222")

        y -= dy

    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"[INFO] group schedule saved: {out_png}")
    print(f"[INFO] group schedule saved: {out_pdf}")
else:
    print("[INFO] --no-gantt specified: group schedule image export skipped.")


# ============================================================
# ② ガントチャート（dfベース表示：あなた指定の形式）

if not NO_GANTT:
    # ============================================================

    # ---- CP-SAT 解からガント用 df を作る ----
    gantt_rows = []

    for d in days:
        ts = slots_by_day[d]
        if not ts:
            continue
        if d in pref_zero_days:
            continue

        timeline = []
        for t in ts:
            chosen = None
            for team in teams:
                if solver.Value(x[(team, d, t)]):
                    chosen = team
                    break
            if chosen is not None:
                timeline.append((t, chosen))

        if not timeline:
            continue

        # 連続区間にまとめる
        cur_team, start_t, prev_t = timeline[0][1], timeline[0][0], timeline[0][0]
        for t, team in timeline[1:]:
            if team == cur_team and t == prev_t + slot:
                prev_t = t
            else:
                gantt_rows.append({
                    "date": d,
                    "group": cur_team,
                    "start": pd.Timestamp(d) + pd.Timedelta(minutes=start_t),
                    "end":   pd.Timestamp(d) + pd.Timedelta(minutes=prev_t + slot)
                })
                cur_team, start_t, prev_t = team, t, t

        gantt_rows.append({
            "date": d,
            "group": cur_team,
            "start": pd.Timestamp(d) + pd.Timedelta(minutes=start_t),
            "end":   pd.Timestamp(d) + pd.Timedelta(minutes=prev_t + slot)
        })

    df_gantt = pd.DataFrame(gantt_rows)

    # ============================================================
    # ② 自動割当用パレット（★既存色と被りにくい）
    # 　・明度・彩度が違う
    # 　・識別しやすい
    # ============================================================
    AUTO_PALETTE = [
        "#EDC948",  # 黄
        "#8CD17D",  # 明るい緑
        "#FF9DA7",  # ピンク
        "#BAB0AC",  # グレー
        "#D37295",  # 紫ピンク
        "#86BCB6",  # 青緑
        "#F1CE63",  # 明るい黄
        "#BAB0AC",
    ]

    # ============================================================
    # ③ 団体 → 色 の最終マップを作る
    # ============================================================
    groups = list(df_gantt["group"].unique())

    def build_color_map(groups, fixed_colors, palette):
        colors = dict(fixed_colors)
        used_colors = set(colors.values())

        palette_iter = iter(c for c in palette if c not in used_colors)

        for g in groups:
            if g not in colors:
                try:
                    colors[g] = next(palette_iter)
                except StopIteration:
                    # パレットが尽きたら matplotlib に任せる
                    colors[g] = None
        return colors

    colors = build_color_map(
        groups=groups,
        fixed_colors=TEAM_COLORS,
        palette=AUTO_PALETTE
    )

    # ============================================================
    # ④ ガントチャート描画
    # ============================================================
    fig, ax = plt.subplots(figsize=(15, 10))
    dates = sorted(df_gantt["date"].unique())

    for i, d in enumerate(dates):
        day_df = df_gantt[df_gantt["date"] == d]
        for _, r in day_df.iterrows():
            s = r["start"].hour * 60 + r["start"].minute
            e = r["end"].hour * 60 + r["end"].minute

            ax.barh(
                i,
                e - s,
                left=s,
                height=0.6,
                color=colors[r["group"]],   # ← None なら自動色
                edgecolor="#555",
                linewidth=1.0
            )

            ax.text(
                (s + e) / 2,
                i,
                r["group"],
                ha="center",
                va="center",
                fontsize=10,
                weight="bold"
            )

    # ============================================================
    # ⑤ 軸・装飾
    # ============================================================
    ax.set_yticks(range(len(dates)))
    ax.set_yticklabels([f"{d.strftime('%Y/%m/%d')}({JP_WD[d.weekday()]})" for d in dates])

    ax.set_xlim(8 * 60, 21 * 60)
    ax.set_xticks(range(8 * 60, 22 * 60, 60))
    ax.set_xticklabels([f"{h}:00" for h in range(8, 22)])

    ax.grid(axis="x", linestyle="--", alpha=0.6)
    ax.invert_yaxis()

    ax.set_title(f"{RUN_TAG} 体育館利用スケジュール（CP-SAT）")


    # ============================================================
    # ⑥ 凡例（固定色＋自動色すべて表示）
    # ============================================================
    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=colors[g])
        for g in groups
    ]

    ax.legend(
        legend_handles,
        groups,
        title="団体名",
        bbox_to_anchor=(1.02, 1),
        loc="upper left"
    )

    plt.tight_layout()


    # ★保存（outputフォルダへ）
    plt.savefig(OUT_RUN_DIR / f"gantt_{RUN_TAG}.png", dpi=300, bbox_inches="tight")
    plt.savefig(OUT_RUN_DIR / f"gantt_{RUN_TAG}.pdf", bbox_inches="tight")
    plt.close()




# ============================================================
# 月合計・時間帯合計（hours）
# monthly_summary_with_zones.csv
# ============================================================
summary = pd.DataFrame({
    "団体名": teams,
    "希望日数": [pref_count[t] for t in teams],
    "合計時間(h)": [solver.Value(totalM[t]) * slot / 60 for t in teams],
    "朝利用合計時間(h)\n(8:30-11:00)": [solver.Value(zone_counts["morning"][t]) * slot / 60 for t in teams],
    "昼利用合計時間(h)\n(11:00-15:00)": [solver.Value(zone_counts["daytime"][t]) * slot / 60 for t in teams],
    "夕利用合計時間(h)\n(15:00-18:00)": [solver.Value(zone_counts["evening"][t]) * slot / 60 for t in teams],
    "夜利用合計時間(h)\n(18:00-21:00)": [solver.Value(zone_counts["night"][t]) * slot / 60 for t in teams],
})


df_summary_sorted = summary.sort_values("合計時間(h)", ascending=False).reset_index(drop=True)

out_path = OUT_RUN_DIR / f"monthly_summary_{RUN_TAG}.csv"
df_summary_sorted.to_csv(out_path, index=False, encoding="utf-8-sig")

print("\n=== Monthly totals (hours) ===")
print(f"\nSaved: {out_path}")
df_summary_sorted

# ---- monthly_summary を表画像として保存 ----

if not NO_GANTT:
    fig, ax = plt.subplots(figsize=(12, 0.6 * (len(df_summary_sorted) + 2)))
    ax.axis("off")

    tbl = ax.table(
        cellText=df_summary_sorted.values,
        colLabels=df_summary_sorted.columns,
        loc="center",
        cellLoc="center"
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.4)
    
    # ==============================
    # ★ ヘッダ行（1行目）だけ高さを増やす
    # ==============================
    ncols = len(df_summary_sorted.columns)

    # いまのヘッダセルの高さを取得
    base_h = tbl[(0, 0)].get_height()

    # 行間を２倍くらいが見やすい
    header_h = base_h * 2

    for c in range(ncols):
        tbl[(0, c)].set_height(header_h)
        # ついでに中央揃え
        tbl[(0, c)].set_text_props(va="center", ha="center", weight="bold")

    plt.tight_layout()
    plt.savefig(OUT_RUN_DIR / f"monthly_summary_{RUN_TAG}.png", dpi=300, bbox_inches="tight")
    plt.close()
# ============================================================
# 5. カレンダー出力（HTML + 画像PNG/PDF）チーム色つき・表示改善版
#  - HTML: チームごとに色付け
#  - 画像: matplotlib.table を使わず「枠+テキスト」を自前描画（潰れにくい）
#  - 出力先: OUT_RUN_DIR 配下（RUN_TAG付き）
#  - --no-gantt のときは画像(PNG/PDF)のみスキップ（HTMLは保存）
#
# 前提（このブロックより前で定義済み）:
#   YEAR, MONTH, slot, days, teams, slots_by_day, pref_days,
#   event_calendar_days, event_days_by_team, tstr,
#   solver, x, OUT_RUN_DIR, RUN_TAG, NO_GANTT
#   （NO_GANTT=False のとき plt が import済み）
# ============================================================

import html as _html
import textwrap
from matplotlib import patches

def _team_color(team: str) -> str:
    return TEAM_COLORS.get(team, "#333333")

print("\n" + "=" * 60)
print("【カレンダー出力（HTML + 画像：チーム色つき）】")
print("=" * 60)

# ------------------------------------------------------------
# (A) 希望団体0の日を特定（表示用）
# ------------------------------------------------------------
pref_zero_days = set()
for d in days:
    if d in event_calendar_days:
        continue
    if not any(d in pref_days.get(t, set()) for t in teams):
        pref_zero_days.add(d)

# ------------------------------------------------------------
# (B) 日ごとの割当を「連続ブロック」で取得（チーム色付け用の構造体）
#     戻り値: list[dict] 例:
#        [{"team": "ULIS...", "s": 510, "e": 600, "is_event": True}, ...]
#     特殊状態:
#        [{"special": "希望団体なし"}] / [{"special": "(利用不可)"}]
# ------------------------------------------------------------
def build_day_blocks(d):
    ts = slots_by_day.get(d, [])

    if d in pref_zero_days:
        return [{"special": "希望団体なし"}]

    if not ts:
        return [{"special": "(利用不可)"}]

    # タイムライン
    timeline = []
    for t in ts:
        chosen = None
        for team in teams:
            if solver.Value(x[(team, d, t)]) == 1:
                chosen = team
                break
        if chosen is None:
            chosen = "(未割当)"
        timeline.append((t, chosen))

    if not timeline:
        return [{"special": "(利用不可)"}]

    # 連続区間
    blocks = []
    cur_team, s, p = timeline[0][1], timeline[0][0], timeline[0][0]
    for t, team in timeline[1:]:
        if team == cur_team and t == p + slot:
            p = t
        else:
            blocks.append((cur_team, s, p + slot))
            cur_team, s, p = team, t, t
    blocks.append((cur_team, s, p + slot))

    out = []
    for team, s, e in blocks:
        if team == "(未割当)":
            continue
        out.append({
            "team": team,
            "s": s,
            "e": e,
            "is_event": ((team, d) in event_days_by_team),
        })

    return out if out else [{"special": "(利用不可)"}]

# ------------------------------------------------------------
# (C) カレンダー週配列（date型のまま保持）
# ------------------------------------------------------------
cal = calendar.Calendar(firstweekday=0)  # 0=月曜開始
weeks = cal.monthdatescalendar(YEAR, MONTH)

dow_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
dow_jp = ["月", "火", "水", "木", "金", "土", "日"]

# ------------------------------------------------------------
# (D) HTML生成（色付き）
# ------------------------------------------------------------
def calendar_to_html(weeks, title="体育館利用スケジュール"):
    # セルHTMLを組み立てる（改行は <br> ではなく div にして崩れにくくする）
    def cell_html(d):
        if d.month != MONTH:
            return ""
        blocks = build_day_blocks(d)

        parts = [f'<div class="daynum">{d.day}</div>']

        # special
        if blocks and "special" in blocks[0]:
            msg = _html.escape(blocks[0]["special"])
            parts.append(f'<div class="special">{msg}</div>')
            return "\n".join(parts)

        # normal blocks
        for b in blocks:
            team = b["team"]
            color = _team_color(team)
            mark = "★" if b["is_event"] else ""
            line = f'{tstr(b["s"])}-{tstr(b["e"])} {mark}{team}'
            parts.append(f'<div class="line" style="color:{color};">{_html.escape(line)}</div>')

        return "\n".join(parts)

    # table body
    body_rows = []
    for w in weeks:
        tds = []
        for d in w:
            tds.append(f"<td>{cell_html(d)}</td>")
        body_rows.append("<tr>" + "".join(tds) + "</tr>")

    thead = "<tr>" + "".join([f"<th>{h}</th>" for h in dow_jp]) + "</tr>"

    html_doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>{_html.escape(title)}</title>
  <style>
    body {{
      font-family: "Meiryo", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", sans-serif;
      padding: 20px;
      color: #222;
    }}
    h1 {{ font-size: 22px; margin: 0 0 12px 0; }}
    .note {{ font-size:12px; color:#666; margin-top:10px; }}

    table.calendar {{
      border-collapse: collapse;
      width: 100%;
      table-layout: fixed;
    }}
    table.calendar th, table.calendar td {{
      border: 1px solid #999;
      vertical-align: top;
      padding: 6px;
      font-size: 12px;
      line-height: 1.35;
      overflow: hidden;
    }}
    table.calendar th {{
      background: #f0f0f0;
      text-align: center;
      font-weight: bold;
      padding: 10px 0;
    }}
    table.calendar td {{
      height: 140px;
      background: #fff;
    }}
    .daynum {{
      font-weight: 700;
      margin-bottom: 4px;
      color: #333;
    }}
    .line {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .special {{
      color: #777;
      font-weight: 600;
    }}
  </style>
</head>
<body>
  <h1>{_html.escape(title)}（{YEAR}年{MONTH}月）</h1>
  <table class="calendar">
    <thead>{thead}</thead>
    <tbody>
      {"".join(body_rows)}
    </tbody>
  </table>
  <div class="note">★ はイベント確定枠</div>
</body>
</html>
"""
    return html_doc

html_str = calendar_to_html(weeks, title="体育館利用スケジュール")
out_html = OUT_RUN_DIR / f"calendar_{RUN_TAG}.html"
with open(out_html, "w", encoding="utf-8") as f:
    f.write(html_str)

print(f"[保存完了] {out_html}")
print("→ ブラウザで開くとカレンダーが表示されます。")

# ------------------------------------------------------------
# (E) 画像（PNG/PDF）生成：枠を描いてテキストを配置（色付き・潰れにくい）
# ------------------------------------------------------------
def save_calendar_image(weeks, out_png: Path, out_pdf: Path, title: str):
    # レイアウト設定
    nrows = len(weeks)            # 週数（だいたい5〜6）
    ncols = 7

    # 1セルのサイズ感（インチ換算）
    cell_w = 3.0
    cell_h = 2.0
    header_h = 0.55
    title_h = 0.6
    pad = 0.2

    fig_w = ncols * cell_w + 2 * pad
    fig_h = nrows * cell_h + header_h + title_h + 2 * pad

    fig = plt.figure(figsize=(fig_w, fig_h))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, ncols)
    ax.set_ylim(0, nrows + (header_h + title_h) / cell_h)  # ざっくり上に余白
    ax.axis("off")

    # タイトル
    ax.text(
        0, nrows + header_h / cell_h + 0.25,
        f"{title}（{YEAR}年{MONTH}月）",
        fontsize=40, fontweight="bold", va="bottom", ha="left", color="#222"
    )
    ax.text(
        ncols, nrows + header_h / cell_h + 0.25,
        "★ はイベント確定枠",
        fontsize=30, va="bottom", ha="right", color="#666"
    )

    # 曜日ヘッダ（背景色：土日だけ少し変える）
    y_header = nrows
    for c in range(ncols):
        rect = patches.Rectangle((c, y_header), 1, header_h / cell_h,
                                 fill=True, linewidth=1.0, edgecolor="#999")
        if c == 5:      # 土
            rect.set_facecolor("#E8F1FF")  # 薄い青
        elif c == 6:    # 日
            rect.set_facecolor("#FFECEC")  # 薄い赤
        else:
            rect.set_facecolor("#F0F0F0")
        ax.add_patch(rect)

        ax.text(
            c + 0.5, y_header + (header_h / cell_h) / 2, dow_jp[c],
            ha="center", va="center", fontsize=20, fontweight="bold", color="#222"
        )


    # セル描画
    for r, week in enumerate(weeks):
        y = (nrows - 1 - r)  # 上から表示
        for c, d in enumerate(week):
            # 背景色：土日だけ薄く変更（対象月外はさらに薄く）
            is_other_month = (d.month != MONTH)
            if is_other_month:
                face = "#FAFAFA"
            else:
                if c == 5:      # 土
                    face = "#F3F8FF"  # 薄い青
                elif c == 6:    # 日
                    face = "#FFF5F5"  # 薄い赤
                else:
                    face = "#FFFFFF"

            rect = patches.Rectangle((c, y), 1, 1, fill=True, linewidth=1.0, edgecolor="#999")
            rect.set_facecolor(face)
            ax.add_patch(rect)

            if is_other_month:
                continue

            # 日付
            ax.text(c + 0.03, y + 0.97, str(d.day),
                    ha="left", va="top", fontsize=18, fontweight="bold", color="#333")

            blocks = build_day_blocks(d)

            # special
            if blocks and "special" in blocks[0]:
                ax.text(c + 0.03, y + 0.83, blocks[0]["special"],
                        ha="left", va="top", fontsize=18, color="#777")
                continue

            # 通常ブロック（1行固定・省略なし）
            line_y = y + 0.83
            line_step = 0.12
            max_lines = 6  # ここは「見た目が崩れない」上限（必要なら増やせる）

            lines = []
            for b in blocks:
                team = b["team"]
                mark = "★" if b["is_event"] else ""
                lines.append((f"{tstr(b['s'])}-{tstr(b['e'])} {mark}{team}", _team_color(team)))

            # 行数が多すぎる場合は、上限以降は表示しない（省略…はしない）
            # 「省略はしたくない」= 文字列を切らない、という意味で解釈してます
            lines = lines[:max_lines]

            for text, color in lines:
                ax.text(
                    c + 0.03, line_y, text,
                    ha="left", va="top",
                    fontsize=13,          
                    color=color,
                    clip_on=True           # ★セル外へはみ出す場合は描画領域でクリップ
                )
                line_y -= line_step

    # 保存
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)

if not NO_GANTT:
    out_png = OUT_RUN_DIR / f"calendar_{RUN_TAG}.png"
    out_pdf = OUT_RUN_DIR / f"calendar_{RUN_TAG}.pdf"
    save_calendar_image(weeks, out_png, out_pdf, title="体育館利用スケジュール")
    print(f"[保存完了] {out_png}")
    print(f"[保存完了] {out_pdf}")
else:
    print("[INFO] --no-gantt 指定のため、カレンダー画像(PNG/PDF)の出力をスキップしました。")
