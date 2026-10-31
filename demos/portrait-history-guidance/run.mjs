import { parseArgs } from 'node:util';
import { loadRealCase, analyzeRealCase, formatMarkdown } from './src/real-case.mjs';

const help = `画像与建议对应 CLI（Node.js 22）

用法：
  node run.mjs --input /本地私有目录/case.json
  node run.mjs --input /本地私有目录/case.json --json
  node run.mjs update --current /本地私有目录/report.json --out /本地私有目录/version-1
  node run.mjs update --current /本地私有目录/new-report.json --previous /本地私有目录/version-1/profile.json --out /本地私有目录/version-2

--input  指向本地 manifest，加载已有 portrait 2.0 与 bundle
--json   输出完整输入与结果 JSON；默认输出中文 Markdown
--help   显示帮助

update 通过 InnoAgent 的 graduate-portrait 更新研究画像，不重新评分。
--date YYYY-MM-DD 与 --date-basis 原文位置 可说明材料记录日期；未知时不填。
update 使用画像脚本已有依赖，以及 INNOAGENT_URL 和模型审计配置。
原 --input 模式仅对照已有结果，不调用模型或要求第三方依赖。
真实原文与结果应只保存在 Git 忽略的本地目录。
`;

try {
  const { values, positionals } = parseArgs({
    options: { input: { type: 'string' }, json: { type: 'boolean' }, help: { type: 'boolean' },
      current: {type: 'string'}, previous: {type: 'string'}, out: {type: 'string'},
      date: {type: 'string'}, 'date-basis': {type: 'string'} },
    strict: true, allowPositionals: true,
  });
  if (positionals.length && (positionals.length !== 1 || positionals[0] !== 'update')) {
    throw new Error('未知子命令');
  }
  if (values.help || (!positionals.length && !Object.keys(values).length)) {
    console.log(help);
  } else if (positionals[0] === 'update') {
    const {runProfileUpdate} = await import('./src/update-profile.mjs');
    await runProfileUpdate(values);
  } else {
    if (!values.input) throw new Error('--json 需要 --input');
    const input = await loadRealCase(values.input);
    const result = analyzeRealCase(input);
    process.stdout.write(values.json
      ? JSON.stringify({ schema_version: 'portrait-history-export-1', input, result }, null, 2) + '\n'
      : formatMarkdown(result));
  }
} catch (error) {
  console.error(`错误：${error.message}\n运行 node run.mjs --help 查看用法。`);
  process.exitCode = 1;
}
