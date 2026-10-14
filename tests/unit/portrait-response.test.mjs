import assert from 'node:assert/strict';
import test from 'node:test';
import {parseStructuredResponse} from '../../.agents/skills/graduate-portrait/scripts/response.mjs';
const fence=String.fromCharCode(96).repeat(3);
const wrap=body=>fence+'json\n'+body+'\n'+fence;
test('响应只接受裸JSON对象或整个响应单个json代码块，字段逐字保留',()=>{
 const data={performance_grade:'invalid-value',quote:'连续原句。',items:[null,'```json']};const json=JSON.stringify(data);
 for(const response of [json,' \n'+json+'\t',wrap(json),' \r\n'+wrap(json).replaceAll('\n','\r\n')+'\t'])assert.deepEqual(parseStructuredResponse(response),data);
});
test('响应拒绝多个块、说明文字、非json围栏、数组、标量及无效JSON',()=>{
 for(const response of [wrap('{}')+'\n'+wrap('{}'),'前言\n'+wrap('{}'),wrap('{}')+'\n后记',fence+'\n{}\n'+fence,fence+'javascript\n{}\n'+fence,'[]',wrap('[]'),'null',wrap('null'),'"string"','42','true','{"a":1,}',wrap('{"a":1,}'),'{} {}',"",null,{}])assert.throws(()=>parseStructuredResponse(response));
});
