// Reusable PR-triage workflow for the jason-pr-triage skill.
//   Workflow({ scriptPath, args: { batches: [[{number,title,author,adds,dels,files,labels,issueCtx}...], ...每批~8条] } })
// issueCtx（可选）：主 agent 预先 join issue 台账拼好的一句话（如 "fixes #6427: confirmed-bug @ grok-api-backend — candid…"）。
// 子 agent 只返回数据；归并与写 ledger 永远由主 agent 完成（见 SKILL.md）。
// 子 agent 绝不写 ledger、绝不操作 GitHub、绝不碰 review 层。
export const meta = {
  name: 'pr-triage-batch',
  description: 'Batch-classify cc-switch GitHub PRs into category + priority via Opus agents',
  phases: [{ title: 'Triage', detail: 'one Opus agent per ~8 PRs', model: 'opus' }],
}

const TRIAGE_SCHEMA = {
  type: 'object',
  required: ['triage'],
  properties: {
    triage: {
      type: 'array',
      items: {
        type: 'object',
        required: ['number', 'category', 'priority', 'priority_reason', 'modules', 'note'],
        properties: {
          number: { type: 'integer' },
          category: { type: 'string', enum: ['bugfix', 'feature', 'preset', 'perf', 'refactor', 'docs', 'i18n', 'ci', 'chore', 'revert'] },
          priority: { type: 'string', enum: ['P0', 'P1', 'P2', 'P3'] },
          priority_reason: { type: 'string' },
          modules: { type: 'array', items: { type: 'string' } },
          note: { type: 'string' },
        },
      },
    },
  },
}

const CONTEXT = `你在为 cc-switch 项目做 PR 分诊。cc-switch 是 Tauri 2 桌面应用，管理/切换多个 AI 编程客户端（Claude Code / Claude Desktop / Codex / Gemini CLI / Grok Build / OpenCode / OpenClaw / Hermes / Pi）的供应商配置，内置本地代理（请求转发、格式转换 Chat/Responses/Gemini↔Anthropic、模型映射、用量计费）、MCP 同步、Skills/Prompts 管理、用量面板。

你的任务是给每个 PR 定分类与处理优先级，帮维护者决定先处理哪些。这不是深审——不逐行审代码，只判断"这是什么、多急、值不值得先看"。`

const RUBRIC = `对清单里每个 PR：
1. 运行 gh pr view <编号> -R farion1231/cc-switch --json title,body,state,isDraft,author,additions,deletions,changedFiles,labels,createdAt,updatedAt --jq '{title, body: (.body // "")[0:3000], state, isDraft, author: .author.login, additions, deletions, changedFiles, labels: [.labels[].name], createdAt, updatedAt}'
2. 运行 gh pr diff <编号> -R farion1231/cc-switch --name-only 2>/dev/null | head -60 看改动文件面；
   分类拿不准再看片段 gh pr diff <编号> | head -200（勿全量拉大 diff）。
3. category 词义：bugfix / feature / preset（供应商预设增改）/ perf / refactor / docs / i18n / ci / chore / revert
4. priority（处理优先级 = 维护者该多快看它）：
   - P0 立即：修**已发版**回归、数据安全/配置丢失类实锤；或清单附注的关联 issue 属热根因组
   - P1 本周：修实锤 bug（关联 issue 已裁 confirmed-bug 的至少 P1）；小 diff 修得对的小修实锤；首次/活跃社区贡献者的合格修复（响应及时性影响社区）
   - P2 有空：方向合理但不急的 feature/refactor/preset；规模大需整块时间的
   - P3 挂起：方向存疑需维护者拍板、>60 天无活动且无人跟、疑似该关闭、纯 chore
   draft 不给 P0/P1。CI 红/有冲突不改变 priority 本身，在 note 注明"候作者"。
5. priority_reason：一句话说清凭什么这个档（回归性/关联 issue 裁决/规模 vs 影响/作者信号）。
6. modules：从 [proxy, codex, claude, gemini, opencode, openclaw, hermes, grok, pi, mcp, skills, prompts, profile, usage, preset, updater, ui, db, i18n, deeplink, packaging, docs] 选 1~2 个，不合适可自拟。
7. note：中文一句话 candid 判断（与已有 PR/issue 撞车点名编号；疑似重复、疑似 AI 灌水、作者信号都写这里），只进本地台账不会公开。

清单行若附「↳ fixes #N: <裁决>」，那是本地 issue 台账的既有裁决，直接采信作为 priority 输入。
返回结构化结果（triage 数组，每个 PR 一条，编号必须与清单一一对应，不得遗漏）。`

const batches = args.batches.map((b, i) => ({
  label: `pr-batch-${i + 1}`,
  intro: `PRs:\n${b
    .map(x => {
      const head = `#${x.number} (@${x.author}, +${x.adds}/-${x.dels}, ${x.files} files)${x.labels && x.labels.length ? ` [${x.labels}]` : ''} ${x.title}`
      return x.issueCtx ? `${head}\n  ↳ ${x.issueCtx}` : head
    })
    .join('\n')}`,
}))

const results = await pipeline(
  batches,
  b =>
    agent(`${CONTEXT}\n\n${b.intro}\n\n${RUBRIC}`, {
      model: 'opus',
      schema: TRIAGE_SCHEMA,
      phase: 'Triage',
      label: b.label,
    }).then(r => {
      log(`${b.label}: ${r ? r.triage.length + ' triaged' : 'FAILED'}`)
      return r
    }),
)

const triage = results.filter(Boolean).flatMap(r => r.triage)
const byPriority = {}
for (const t of triage) byPriority[t.priority] = (byPriority[t.priority] || 0) + 1
const failedBatches = results.map((r, i) => (r ? null : batches[i].label)).filter(Boolean)
return { triage, byPriority, failedBatches }
