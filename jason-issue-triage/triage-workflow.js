// Reusable triage workflow for the issue-triage skill.
// 两种输入模式（子 agent 均只返回数据；归并根因组与写 ledger 永远由主 agent 完成，见 SKILL.md）：
//   小批量: Workflow({ scriptPath, args: { batches: [[{number,title,labels}...], ...], groups } })
//   大批量: Workflow({ scriptPath, args: { batchFile: '<每行 {number,title,labels} 的 JSONL>',
//                                          total: N, batchSize: 10, groups | groupsFile } })
//     — groupsFile: 组库大时传文件路径（每行 {id,title,module}），agent 自己 cat，免得内联膨胀 prompt。
//     — 大批量模式 return 只含统计摘要；600 条明细从 journal.jsonl 用 jq 提取，勿灌主上下文。
export const meta = {
  name: 'issue-triage-batch',
  description: 'Batch-triage cc-switch GitHub issues into verdicts via Opus agents',
  phases: [{ title: 'Triage', detail: 'one Opus agent per ~10 issues', model: 'opus' }],
}

const TRIAGE_SCHEMA = {
  type: 'object',
  required: ['triage'],
  properties: {
    triage: {
      type: 'array',
      items: {
        type: 'object',
        required: ['number', 'verdict', 'modules', 'note'],
        properties: {
          number: { type: 'integer' },
          verdict: { type: 'string', enum: ['confirmed-bug', 'needs-info', 'cannot-repro', 'question', 'by-design', 'upstream', 'invalid', 'duplicate', 'feature-request'] },
          modules: { type: 'array', items: { type: 'string' } },
          suggested_group: { type: ['string', 'null'] },
          note: { type: 'string' },
        },
      },
    },
  },
}

const groupsBlock = args.groupsFile
  ? `已有根因组库：先运行 cat ${args.groupsFile} 查看（每行 {id,title,module}）。优先复用其 id，确无匹配再自拟新名。`
  : (args.groups && args.groups.trim())
    ? `已有根因组库（优先复用其 id，确无匹配再自拟新名）：\n${args.groups.trim()}`
    : '当前根因组库为空，你的建议就是种子。'

const CONTEXT = `你在为 cc-switch 项目做 GitHub issue 初诊。cc-switch 是 Tauri 2 桌面应用，管理/切换多个 AI 编程客户端（Claude Code / Codex / Gemini CLI / OpenCode / OpenClaw / Hermes / Claude Desktop）的供应商配置，内置本地代理（请求转发、格式转换 Chat/Responses/Gemini↔Anthropic、模型映射、用量计费）、MCP 同步、Skills/Prompts 管理、用量面板。`

const RUBRIC = `对清单里每个 issue：
1. 运行 gh issue view <编号> -R farion1231/cc-switch --json title,body,labels,comments --jq '{title, body: (.body // "")[0:3000], labels: [.labels[].name], comments: [.comments[0:3][] | {author: .author.login, body: (.body // "")[0:800]}]}'
2. 给出裁决 verdict，词义：
   - confirmed-bug：描述+证据足以确认是 cc-switch 的缺陷
   - needs-info：方向可信但信息不足以定位（缺日志/版本/复现步骤）
   - cannot-repro：描述完整但明显无法按其步骤复现或自相矛盾
   - question：使用咨询，非缺陷
   - by-design：行为符合设计
   - upstream：根因在上游（AI 客户端本身、供应商 API、npm 镜像等），非 cc-switch 代码
   - invalid：无效（垃圾、空、与项目无关）
   - feature-request：功能请求（enhancement 类都算，除非其实是 bug 报告）
   - duplicate：只在你几乎确定与本批次另一 issue 或已有组同根因时用，且必须在 suggested_group 给同一组名
3. modules：从 [proxy, codex, claude, gemini, opencode, openclaw, hermes, grok, mcp, skills, prompts, profile, usage, preset, updater, ui, db, i18n, deeplink, packaging, docs] 选 1~2 个，不合适可自拟
4. suggested_group：仅 confirmed-bug/duplicate/upstream 需要，kebab-case 短语描述根因（如 codex-subagent-empty-payload）；症状相同但根因可能不同时宁可分开。
5. note：中文一句话 candid 判断（根因猜测/可信度/归属），只进本地台账不会公开。

注意：症状相似 ≠ 同根因；enhancement label 但内容是 bug 报告的按 bug 处理；正文为空或只有截图且无法判断的给 needs-info；评论区或关联 commit 显示可能已修复的，在 note 里注明"疑已修复"及依据。

返回结构化结果（triage 数组，每个 issue 一条，编号必须与清单一一对应，不得遗漏）。`

let batches
if (args.batches) {
  batches = args.batches.map((b, i) => ({
    label: `triage-batch-${i + 1}`,
    intro: `Issues:\n${b.map(x => `#${x.number} [${x.labels}] ${x.title}`).join('\n')}`,
  }))
} else {
  const size = args.batchSize || 10
  const n = Math.ceil(args.total / size)
  batches = Array.from({ length: n }, (_, i) => {
    const start = i * size + 1
    const end = Math.min((i + 1) * size, args.total)
    return {
      label: `triage-${start}-${end}`,
      intro: `你负责的 issue 清单：先运行 sed -n '${start},${end}p' ${args.batchFile}\n每行是一条 JSON {number,title,labels}，title 可能被截断，正文以 gh issue view 为准。`,
    }
  })
}

const results = await pipeline(
  batches,
  (b, _orig, i) => agent(`${CONTEXT}\n\n${b.intro}\n\n${RUBRIC}\n\n${groupsBlock}`, {
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
const byVerdict = {}
for (const t of triage) byVerdict[t.verdict] = (byVerdict[t.verdict] || 0) + 1
const failedBatches = results.map((r, i) => (r ? null : batches[i].label)).filter(Boolean)

// 大批量时明细留在 journal.jsonl，这里只回传摘要
if (args.batchFile) return { total: triage.length, byVerdict, failedBatches }
return { triage, byVerdict, failedBatches }
