import { randomUUID } from 'node:crypto';
import Fastify from 'fastify';
import swagger from '@fastify/swagger';
import swaggerUI from '@fastify/swagger-ui';
import { bundleSchema, portraitSchema, validateBundle, validatePortrait, loadConfiguration, runWorkflow, aResultSchema, validateAResult } from '../skill-bridge.mjs';
import type { PortraitRequest, PortraitJob, PublicError, Workflow } from './contracts.js';
import { portraitExamples } from './examples.js';

interface ServerOptions {
  workflow?: Workflow;
  maxConcurrent?: number;
  maxJobs?: number;
  ttlMs?: number;
  timeoutMs?: number;
  now?: () => number;
}

const object = (properties: Record<string, unknown>, required = Object.keys(properties)) => ({
  type: 'object', properties, required, additionalProperties: false,
});
const errorSchema = object({ error: object({ code: { type: 'string' }, message: { type: 'string' } }) });
const publicErrorSchema = object({ code: { type: 'string' }, message: { type: 'string' } });
const jobSchema = object({
  id: { type: 'string', format: 'uuid' },
  status: { type: 'string', enum: ['running', 'completed', 'failed'] },
  createdAt: { type: 'string', format: 'date-time' },
  expiresAt: { type: 'string', format: 'date-time' },
  completedAt: { type: 'string', format: 'date-time' },
  portrait: { $ref: 'GraduatePortrait#' },
  error: publicErrorSchema,
}, ['id', 'status', 'createdAt', 'expiresAt']);

const messages: Record<string, string> = {
  CONFIGURATION: '服务端 InnoAgent 配置不完整，请检查本地配置。',
  INVALID_INPUT: '材料或规则配置未通过画像校验。',
  REMOTE_TIMEOUT: 'InnoAgent 或模型调用超时。',
  REMOTE_NETWORK: '无法连接 InnoAgent 或模型服务。',
  REMOTE_HTTP: 'InnoAgent 或模型服务返回错误。',
  QUOTA_EXHAUSTED: '模型服务配额已用尽。',
  STRUCTURED_OUTPUT: '画像输出未通过结构或证据校验。',
  INNOAGENT_PROTOCOL: 'InnoAgent 响应不符合约定。',
  TOOL_APPROVAL_REQUIRED: '阶段任务需要额外交互审批，本地已停止等待；上游取消结果需确认，重试前请检查 InnoAgent。',
  ABORTED: '本地已停止等待；上游取消结果需确认，重试前请检查 InnoAgent。',
  JOB_TIMEOUT: '画像任务超过等待时间限制，上游可能仍在执行，确认结束前请勿重试。',
  GENERATION_FAILED: '画像生成失败，请检查本地服务配置。',
};
function publicError(error: unknown): PublicError {
  const code = error && typeof error === 'object' && 'code' in error && typeof error.code === 'string' && messages[error.code]
    ? error.code : 'GENERATION_FAILED';
  return { code, message: messages[code]! };
}

export async function createPortraitServer(options: ServerOptions = {}) {
  const configuration = await loadConfiguration();
  const workflow = options.workflow ?? runWorkflow;
  const now = options.now ?? Date.now;
  const maxConcurrent = options.maxConcurrent ?? 2;
  const maxJobs = options.maxJobs ?? 20;
  const ttlMs = options.ttlMs ?? 30 * 60_000;
  const timeoutMs = options.timeoutMs ?? 5 * 60_000;
  if (![maxConcurrent, maxJobs, ttlMs, timeoutMs].every(value => Number.isSafeInteger(value) && value > 0) || maxConcurrent > maxJobs) {
    throw new Error('invalid portrait server limits');
  }
  const jobs = new Map<string, PortraitJob>();
  const active = new Map<string, { controller: AbortController; timer: NodeJS.Timeout }>();
  const prune = () => {
    for (const [id, job] of jobs) if (!active.has(id) && Date.parse(job.expiresAt) <= now()) jobs.delete(id);
  };
  const app = Fastify({
    logger: false, bodyLimit: 1_048_576,
    ajv: { customOptions: { removeAdditional: false, coerceTypes: false, useDefaults: false, allowUnionTypes: true } },
  });
  await app.register(swagger, {
    refResolver: { buildLocalReference: json => String(json.$id) },
    transformObject: document => {
      if (!('openapiObject' in document)) return document.swaggerObject;
      const requestBody = document.openapiObject.paths?.['/api/portraits']?.post?.requestBody;
      if (requestBody && !('$ref' in requestBody)) {
        const mediaType = requestBody.content?.['application/json'];
        if (mediaType) mediaType.examples = portraitExamples;
      }
      return document.openapiObject;
    },
    openapi: {
      openapi: '3.0.3',
      info: {
        title: 'InnoGrad 研究生画像原型 API', version: '0.2.0',
        description: `画像与隐性评价采用 2.0 契约，材料 bundle 与事实抽取保持 1.0。默认 implicit_only 只执行 B 的隐性评价，显性部分为空且待补 A；可传 aResult 合并 A 结果，或选择 bundle_pipeline 在原型内抽取。七领域不定级，每项分开记录证据状态和三档表现。通过真实 InnoAgent graduate-portrait Skill 生成待人工复核的草稿。输入为已解析材料，不含 OCR。任务仅存于进程内，默认保留30分钟，重启丢失；最多20条、同时2次本地执行，整体等待${timeoutMs / 1000}秒超时（默认300秒，启动配置范围1–900秒）。超时只停止本地等待，InnoAgent后端可能继续执行，晚到结果不保存；确认上游执行结束前请勿重试。POST每次创建新任务，重复提交会再次生成。`,
      },
      tags: [{ name: '画像' }, { name: '规则' }],
    },
  });
  await app.register(swaggerUI, { routePrefix: '/docs', staticCSP: true, uiConfig: { docExpansion: 'list' } });
  app.addSchema({ ...bundleSchema, $id: 'ParsedMaterialBundle' });
  app.addSchema({ ...aResultSchema(configuration.rules), $id: 'AResult' });
  app.addSchema({ ...portraitSchema, $id: 'GraduatePortrait' });
  app.addSchema({ ...jobSchema, $id: 'PortraitJob' });
  app.setErrorHandler((error, _request, reply) => {
    const problem = error as { validation?: unknown; statusCode?: number };
    const statusCode = problem.validation || problem.statusCode === 400 ? 400 : problem.statusCode === 413 ? 413 : problem.statusCode === 415 ? 415 : 500;
    reply.code(statusCode).send({ error: {
      code: statusCode === 400 ? 'INVALID_REQUEST' : statusCode === 413 ? 'PAYLOAD_TOO_LARGE' : statusCode === 415 ? 'UNSUPPORTED_MEDIA_TYPE' : 'INTERNAL_ERROR',
      message: statusCode === 400 ? '请求未通过 JSON 结构校验。' : statusCode === 413 ? '材料超过1 MiB请求上限。' : statusCode === 415 ? '请使用 application/json 请求。' : '服务处理失败。',
    } });
  });
  app.setNotFoundHandler((_request, reply) => reply.code(404).send({ error: { code: 'NOT_FOUND', message: '接口或任务不存在。' } }));

  app.post<{ Body: PortraitRequest }>('/api/portraits', {
    schema: {
      tags: ['画像'], operationId: 'createPortrait', summary: '提交画像生成任务',
      description: '默认 implicit_only：仅传 bundle 时只评价隐性部分，explicit 为 null、explicit_status 为 pending。aResult 经身份、任务、材料指纹、版本和出处校验后原样合并；即使 mode 为 bundle_pipeline，有 A 结果时也只执行评价。未传 A 时可选择 bundle_pipeline 先抽取并计算显性部分。异步调用 InnoAgent。202不表示已生成，使用Location或GET查询任务。相同输入再次POST仍会新建任务。失败任务的error提供固定错误类别，不包含上游原文或密钥。超时停止本地等待，上游执行可能继续，确认其结束前请勿重试。',
      body: object({
        bundle: { $ref: 'ParsedMaterialBundle#' },
        aResult: { $ref: 'AResult#', description: 'A 已计算的显性结果；验证通过后只执行隐性评价并原样合并。' },
        mode: { type: 'string', enum: ['implicit_only', 'bundle_pipeline'], description: '默认 implicit_only：仅评价隐性部分。bundle_pipeline：未传 aResult 时在原型内先抽取并计算显性部分；传 A 时优先合并 A。' },
      }, ['bundle']),
      response: { 202: { $ref: 'PortraitJob#' }, 400: errorSchema, 413: errorSchema, 415: errorSchema, 422: errorSchema, 503: errorSchema },
    },
  }, async (request, reply) => {
    try { validateBundle(request.body.bundle); }
    catch { return reply.code(422).send({ error: { code: 'INVALID_INPUT', message: '材料的学生、期间、文档或段落信息不一致。' } }); }
    if (request.body.aResult) {
      try { validateAResult(request.body.bundle, request.body.aResult, configuration.rules); }
      catch { return reply.code(422).send({ error: { code: 'INVALID_A_RESULT', message: 'A 交接的学生、任务、期间、材料版本、规则或出处不一致。' } }); }
    }
    prune();
    if (active.size >= maxConcurrent || jobs.size >= maxJobs) {
      return reply.header('Retry-After', '30').code(503).send({ error: { code: 'CAPACITY_EXCEEDED', message: '画像任务容量已满，请稍后重试。' } });
    }
    const id = randomUUID();
    const job: PortraitJob = { id, status: 'running', createdAt: new Date(now()).toISOString(), expiresAt: new Date(now() + ttlMs).toISOString() };
    const controller = new AbortController();
    jobs.set(id, job);
    const fail = (error: PublicError) => {
      job.status = 'failed'; job.error = error; job.completedAt = new Date(now()).toISOString();
    };
    const timer = setTimeout(() => {
      fail({ code: 'JOB_TIMEOUT', message: messages.JOB_TIMEOUT! });
      controller.abort();
    }, timeoutMs);
    timer.unref();
    active.set(id, { controller, timer });
    void Promise.resolve().then(() => workflow({ bundle: request.body.bundle, mode: request.body.aResult ? 'implicit_only' : request.body.mode ?? 'implicit_only', ...(request.body.aResult ? { aResult: request.body.aResult } : {}), signal: controller.signal }))
      .then(portrait => {
        if (controller.signal.aborted) return;
        try { validatePortrait(portrait); }
        catch { fail({ code: 'STRUCTURED_OUTPUT', message: messages.STRUCTURED_OUTPUT! }); return; }
        job.portrait = portrait; job.status = 'completed'; job.completedAt = new Date(now()).toISOString();
      })
      .catch(error => { if (!controller.signal.aborted) fail(publicError(error)); })
      .finally(() => { clearTimeout(timer); active.delete(id); prune(); });
    return reply.header('Location', `/api/portraits/${id}`).code(202).send({ ...job });
  });

  app.get<{ Params: { id: string } }>('/api/portraits/:id', {
    schema: {
      tags: ['画像'], operationId: 'getPortrait', summary: '查询任务状态与画像草稿',
      description: '运行中返回running；完成后返回completed与portrait；失败返回failed与error。不存在、已过期或服务重启后的任务返回404。画像字段review_status始终为draft。',
      params: object({ id: { type: 'string', minLength: 1, maxLength: 100 } }),
      response: { 200: { $ref: 'PortraitJob#' }, 400: errorSchema, 404: errorSchema },
    },
  }, async (request, reply) => {
    prune();
    const job = jobs.get(request.params.id);
    if (!job) return reply.code(404).send({ error: { code: 'NOT_FOUND', message: '任务不存在或已过期。' } });
    return job;
  });
  app.get('/api/portrait-config', {
    schema: {
      tags: ['规则'], operationId: 'getPortraitConfiguration', summary: '读取当前显性规则与隐性评价标准',
      description: '读取Skill版本化配置，不提供写入接口，不返回模型、密钥或环境变量。缺少制度原文的阈值保持null，画像检查为pending_rule。',
      response: { 200: object({ rules: { type: 'object', additionalProperties: true }, rubric: { type: 'object', additionalProperties: true } }), 500: errorSchema },
    },
  }, () => loadConfiguration());
  app.get('/openapi.json', { schema: { hide: true } }, () => app.swagger());
  const sweep = setInterval(prune, Math.min(ttlMs, 60_000));
  sweep.unref();
  app.addHook('onClose', async () => {
    clearInterval(sweep);
    for (const { controller, timer } of active.values()) { clearTimeout(timer); controller.abort(); }
    jobs.clear();
  });
  return app;
}
