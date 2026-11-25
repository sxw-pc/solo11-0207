# 手语现场转播交付采录台

活动导播、手语班长和回放交付员用同一份离线 SQLite 记录议程、术语预演、译员接力和画中画审样。报告给出具体哪些秒段缺少可交付手语，以及哪一份回放可签发。使用 Python 3.11+ 标准库，无安装依赖。画面证据由审样员录入，工具以这些坐标及其版本裁决可读性。

```sh
python -B -m sign_broadcast --db event.sqlite demo fixtures/demo.json
python -B -m sign_broadcast --db event.sqlite agenda main
python -B -m sign_broadcast --db event.sqlite crew main
python -B -m sign_broadcast --db event.sqlite picture live-b0
python -B -m sign_broadcast --db event.sqlite delivery main
python -B -m sign_broadcast --db event.sqlite delivery main --asset replay-main
python -B -m sign_broadcast --db event.sqlite splice fixtures/splice-main.json
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
| 拼片 | `splice PLAN` | 只读接收剪辑台导出的双轨片段清单。同一目标秒两轨各需唯一来源，且指向同一场次的同一源秒；手语源素材在该秒须有当版可交付证据，多来源歧义保留并待补。从片段接缝进入源接棒秒时，正前方须完整保留同一接棒的 3 秒准备上下文（可跨片段，各段来源均须合证），或采认绑定节目源、手语素材与当前译播版本的独立开场回执；回执过期或其后源秒失证都回到对应原因。报告给出目标区间、两个来源区间、所用准备上下文或回执，以及去重后的待补秒数。 |

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

## 拼片接收

剪辑台把节目轨与手语轨分别导出后，`splice PLAN` 以读事务接收本地拼片清单，不写入数据库。清单 `fragments` 每条声明 `track`（`program` 或 `sign`）、目标半开区间 `target`、等长源区间 `source`、源素材 `asset`+`rev` 与源活动场次 `session`；`receipts` 可选，每条独立开场回执声明 `id`、启用源秒 `source`、绑定的 `program_asset`/`sign_asset` 及版本、`turn`+`turn_rev` 与 `approved`。源素材是否可交付以 `delivery` 报告为准，接力见证失效经源证据传导到引用它的拼片秒点。`fixtures/splice-main.json` 是主场 120 秒接棒的短版：双轨 `[100,117)` 接 `[120,140)`，附源 120 秒的独立开场回执，交付 37 秒；补录双轨 `[117,120)` 后，这三秒作为原接棒的准备上下文继承，交付 40 秒。
