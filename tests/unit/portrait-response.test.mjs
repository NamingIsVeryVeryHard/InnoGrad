import assert from 'node:assert/strict';
import test from 'node:test';
import {parseStructuredResponse} from '../../skills/graduate-portrait/scripts/response.mjs';
const fence=String.fromCharCode(96).repeat(3);
const wrap=body=>fence+'json\n'+body+'\n'+fence;
test('响应只接受裸JSON对象或整个响应单个json代码块，字段逐字保留',()=>{
 const data={performance_grade:'invalid-value',quote:'连续原句。',items:[null,'```json']};const json=JSON.stringify(data);
 for(const response of [json,' \n'+json+'\t',wrap(json),' \r\n'+wrap(json).replaceAll('\n','\r\n')+'\t'])assert.deepEqual(parseStructuredResponse(response),data);
});
test('响应拒绝多个块、说明文字、非json围栏、数组、标量及无效JSON',()=>{
 for(const response of [wrap('{}')+'\n'+wrap('{}'),'前言\n'+wrap('{}'),wrap('{}')+'\n后记',fence+'\n{}\n'+fence,fence+'javascript\n{}\n'+fence,'[]',wrap('[]'),'null',wrap('null'),'"string"','42','true','{"a":1,}',wrap('{"a":1,}'),'{} {}',"",null,{}])assert.throws(()=>parseStructuredResponse(response));
});

test('JSON_PARSE反馈只保留真实SyntaxError数字位置并要求检查闭合与多行输出',async()=>{
 const {repairFeedback}=await import('../../skills/graduate-portrait/scripts/validation.mjs');
 const body='{\n  "PRIVATE_PAYLOAD": [1}\n}';let raw;try{JSON.parse(body);}catch(error){raw=error;}
 for(const parse of [()=>JSON.parse(body),()=>parseStructuredResponse(body),()=>parseStructuredResponse(wrap(body))]){
  let error;try{parse();}catch(e){error=e;}assert.ok(error instanceof SyntaxError);
  const feedback=repairFeedback(error);assert.match(feedback,/JSON_PARSE/);assert.match(feedback,/"offset":\d+/);assert.match(feedback,/"line":\d+/);assert.match(feedback,/"column":\d+/);assert.match(feedback,/数组.*对象.*闭合/);assert.match(feedback,/多行.*缩进/);assert.match(feedback,/非minified/);assert.ok(!feedback.includes('PRIVATE_PAYLOAD'));assert.ok(!feedback.includes(raw.message));
 }
 const unknown=repairFeedback(new SyntaxError('PRIVATE_UNKNOWN_SYNTAX'));assert.match(unknown,/JSON_PARSE/);assert.ok(!unknown.includes('PRIVATE_UNKNOWN_SYNTAX'));assert.ok(!unknown.includes('"offset"'));
});
