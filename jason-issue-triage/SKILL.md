---
name: jason-issue-triage
description: Sync GitHub issues into the private local triage ledger (~/.cc-switch-triage), batch-triage new ones into verdicts + root-cause groups via an Opus workflow, analyze problem hotspots, and answer "which issues does this release fix". Candid notes stay local — never posted to GitHub.
argument-hint: "[stats | release [tag] | backfill N | <issue numbers…>] — 默认：增量同步 + 分诊新 issue"
---

# Issue Triage Ledger

GitHub 是 issue 事实的 SSOT；本台账只存 GitHub 上没有的**裁决增量**：verdict、根因组、
修复关联、candid 备注。cache 可随时重建，ledger/groups 是唯一需要保护的数据。

```
~/.cc-switch-triage/
  ledger.jsonl        # 裁决（人/AI 写），一行一 issue —— 唯一权威裁决记录
  groups.jsonl        # 根因组（跨 issue 归并）
  cache/issues.jsonl  # GitHub 元数据镜像（sync.sh 生成，可随时重建，勿手改）
  sync-state.json     # 上次同步时间戳
```

## Schema

**ledger.jsonl** 一行一条：

```json
{"number": 5832, "verdict": "confirmed-bug", "group": "proxy-cache-prefix", "modules": ["proxy"], "evidence": null, "fixed_in": null, "note": "candid 一句话：根因判断/用户描述可信度/上下游归属", "triaged_at": "2026-07-30", "updated_at": "2026-07-30"}
```

verdict 状态机（只进不退，唯一例外=修复被 revert 时回退并注记；`evidence` 在 fix-committed 起**必填** commit/PR 链接）：

```
needs-info / cannot-repro / question / by-design / upstream / invalid   （终态或等待态）
duplicate（必填 group，指向根因组）
feature-request → fix-committed → fix-released
confirmed-bug   → fix-committed → fix-released → verified-closed
```

**groups.jsonl**：`{"id": "kebab-slug", "title": "一句话根因", "module": "proxy|mcp|ui|db|usage|preset|updater|i18n|...", "status": "open|fixed", "note": "", "created_at": "..."}`

## 默认流程（无参数）

1. 跑 `bash .claude/skills/jason-issue-triage/sync.sh`（首次自动全量，之后增量）。
   脚本输出未分诊 open 数 + 最近活跃的 top 30 清单。
2. **合并回写**：扫上次同步以来 merged 的 PR，解析 `Fixes/Closes/Resolves #N` 与 `Refs #N`。
   优先直接消费 `cache/prs.jsonl` 里解析好的 `fixes`/`refs` 字段（跑过 `/jason-pr-triage`
   的 sync 即新鲜）；没有该 cache 再退回
   `gh pr list --state merged --search "merged:>=<sync-state 时间戳>"` 取 body 自行解析：
   - Fixes 类声称且 issue 已有裁决 → verdict 推进 `fix-committed`，evidence=PR 链接，note 追加「PR #N 合并声称修复，待发版验证」。**声称≠事实**（#5508 教训），验证留给 `release` 流程，此处只入队。
   - `Refs` 类 → 仅 note 追加「相关修复 PR #N 已合并」，verdict 不动（伞状 issue 一个 PR 只修一条链）。
   - 被声称修复但尚未分诊的 issue → 不代填 verdict，列入本次分诊清单优先处理。
   - 发现 revert（标题 `Revert`/gh 关联）→ 回滚对应标记并注记。
3. 对清单批量分诊（见下方「批量分诊执行方式」）。
4. 汇总报告：本次各 verdict 计数、合并回写标记清单、新建根因组、值得注意的聚集（同组 ≥3 条要点名）、剩余 backlog 数。

## 批量分诊执行方式

**> 10 条：必须用 Workflow 编排，子 agent 用 `model: 'opus'`**（Jason 指定，与"子 agent 用
Opus"全局规则一致；2026-08-13 起由 Sonnet 改为 Opus）。≤ 10 条直接 inline 分诊。

现成脚本：`.claude/skills/jason-issue-triage/triage-workflow.js`（勿每次重写）。调用：

```
Workflow({ scriptPath: '<repo>/.claude/skills/jason-issue-triage/triage-workflow.js',
           args: { batches: [[{number,title,labels}, ...每批~10条], ...],
                   groups: "<groups.jsonl 全文，空则传空串>" } })
```

- 子 agent 自己拉正文（body 截 3000 字符、评论前 3 条），schema 强制返回
  `{triage: [{number, verdict, modules, suggested_group, note}]}` —— 子 agent **只返回数据，
  绝不写 ledger、绝不操作 GitHub**。
- 主 agent 收齐后做全局归并：suggested_group 同根因的合并、映射/新建 groups.jsonl 条目，
  补 `triaged_at`/`updated_at`（当天日期），统一写 ledger（append 新行；重分诊时 jq 滤旧行
  再 append）。归并和写文件永远在主 agent。

## 子命令

**`stats`** — 不触发分诊，纯 jq 分析后输出简表：
open 按 label 分布（cache）、按根因组分布（ledger join groups，点名 top 组）、verdict 分布、
按月新增趋势（created_at）。

**`release [tag]`** — 回答"这个版本修了哪些 issue"：
1. 范围：给了 tag 则取「上一 tag..该 tag」，否则「最新 tag..HEAD」（`git describe --tags --abbrev=0`）。
2. 候选 = `git log` 提到 `#NNNN` 的 + ledger 里 verdict ∈ {confirmed-bug, fix-committed} 且
   evidence commit 落在范围内的（合并回写会持续把 fix-committed 这批喂全，git log 扫描是兜底）。
3. **逐条验证**：读 commit diff，确认真的覆盖该 issue 的场景 —— 不做模式匹配关闭
   （v3.18.0 教训：未修缺口不能当已修关）。
4. 验证通过的 → ledger 更新为 fix-released + fixed_in 版本号。
5. 产出**建议关闭清单 + 逐条关闭评论草稿**交 Jason 审。**绝不自己关 issue / 发评论。**

**`backfill N`** — 分诊最近活跃的 N 条未分诊 open issue（同批量流程，N 大时 workflow 分批照跑）。
首次回填建议 100~200，closed 的历史 issue 懒回填（被查重引用到才补）。

**`<issue numbers…>`** — 只分诊/重分诊这些编号（inline，适合深挖单条：可读全部评论、查关联 commit）。

## 红线

- **candid note 永不出现在 GitHub**（评论、关闭理由、release note 都不行）。
- **绝不自动关 issue、发评论、改 label** —— 一切对外动作只产出草稿清单，Jason 审后执行。
- fix-committed 起必须带 evidence，无 commit 链接不得进该状态。
- 台账目录永远在 `~/.cc-switch-triage/`，不进公开仓库；cache 不手改，坏了 `sync.sh --full` 重建。
- duplicate 裁决前先看根因是否真同源（教训：#2942/#3064/#3937 症状同、根因异，不是重复）。
