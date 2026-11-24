# 手语现场转播交付采录台

活动导播、手语班长和回放交付员用同一份离线 SQLite 记录议程、术语预演、译员接力和画中画审样。报告给出具体哪些秒段缺少可交付手语，以及哪一份回放可签发。使用 Python 3.11+ 标准库，无安装依赖。画面证据由审样员录入，工具以这些坐标及其版本裁决可读性。

```sh
python -B -m sign_broadcast --db event.sqlite demo fixtures/demo.json
python -B -m sign_broadcast --db event.sqlite agenda main
python -B -m sign_broadcast --db event.sqlite crew main
python -B -m sign_broadcast --db event.sqlite picture live-b0
python -B -m sign_broadcast --db event.sqlite delivery main
python -B -m sign_broadcast --db event.sqlite delivery main --asset replay-main
python -B -m sign_broadcast --db event.sqlite recompute
python -B -m unittest discover -s tests -v
```

`demo` 初始化数据库并为具备完整证据的主场回放签发。`ingest` 接受本地 JSON 数组，数据形状见 `fixtures/demo.json` 的 `capture`。同类型、同 `id`、同 `rev` 的等值记录可原样重放。冲突记录回滚整个批次，最大版本参与现行计算。凡下游记录明确绑定上游版本，旧记录保留在库中，并须补录相应的新依据才能覆盖当前交付。时间使用同一个活动时钟的整数秒，区间左闭右开。画面矩形使用 `[left, top, right, bottom]` 像素边界。

## 工位裁决

| 工位 | 入口 | 判定依据 |
| --- | --- | --- |
| 议程 | `agenda SESSION` | 签约场次内每段需恰好一个有效议程条目，列出空档、重叠、越界。每个必备术语需要当前条目版本及手语语种的预演，通过与拒绝并存时挂起。 |
| 译员班次 | `crew SESSION` | 每段需恰好一位在岗译员。时段和语种证书合并覆盖，有否决即扣留。同人其他场次的实际译播可与当班或接力预备冲突。不同译员交棒需两人都能完成前 3 秒预备和唯一现行见证。失败给接棒起点最多 3 秒的缺口。 |
| 画面 | `picture REVIEW` | 按译播段、画中画版式及回放素材版本定位审样。同一秒段的冲突版式或任一审样拒绝给出画面缺口。边距至少 12 像素，画中画至少 160×160，译员关键区至少 100×120 且完全在画中画内。遮挡矩形与关键区正面积相交时扣留，边界接触可接受。 |
| 交付 | `delivery SESSION [--asset ASSET]` | 按场次时间轴同时覆盖议程、术语、译员和画面。回放还须覆盖当前场次的素材版本与播放范围，并拥有该素材专属审样。重叠失败原因合并到相同时段，秒数只计一次。 |

`review.asset="-"` 与 `asset_rev=0` 表示现场画面。回放审样必须带明确的素材身份与版本。`recompute` 使用一个读事务从持久的工位修订和签发记录重建所有视图。外部媒体播放、字幕校准、演出版权和第三方发布不在此工具的范围。

## 修订与重签

初始样例的主场接力合格。直播 `[120,126)` 的译员关键区被角标遮挡，主场回放使用单独的样本，0 秒缺口且已签发。分场 `side` 有 10 秒交付缺口。

```sh
python -B -m sign_broadcast --db event.sqlite ingest fixtures/late-overlay.json
python -B -m sign_broadcast --db event.sqlite delivery main --asset replay-main
python -B -m sign_broadcast --db event.sqlite ingest fixtures/repair-overlay.json
python -B -m sign_broadcast --db event.sqlite delivery main --asset replay-main
python -B -m sign_broadcast --db event.sqlite resign replay-main BASIS director
```

补录回放角标后，回放缺口变为 40 秒，旧凭证失效。修正使角标只接触关键区边界，再读取回放报告并把 `BASIS` 换成报告的 `basis`。写事务会复核当前可交付性及依据，相同有效依据的重签返回已有编号。每份历史签发保留当时的依据及证据快照。

`late-agenda.json` 和 `repair-agenda.json` 可在另一份样例库演示议程换版及逐项重绑定，修复后使用当前 `basis` 重签。`repair-live.json` 单独修复直播角标。两路修正各影响自身的画面证据。

## 录制设备状态采录

`python -B -m sign_broadcast --db event.sqlite recorder-health main fixtures/recorder-health.json` 读取管理终端导出的设备状态。首个观察前保留未知时间，观察的状态沿用到下一次变更或包边界。设备服务秒和观察原件可在同一报告核对，这个查询不修改场次或法律声明。
