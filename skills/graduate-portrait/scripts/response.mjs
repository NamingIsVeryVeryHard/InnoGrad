export function jsonParseLocation(error) {
  if(!(error instanceof SyntaxError))return {};
  const match=/\bat position (\d+)(?: \(line (\d+) column (\d+)\))?$/.exec(error.message);
  const lineOnly=/\b(?:at )?line (\d+) column (\d+)(?: of the JSON data)?$/.exec(error.message);
  const candidates=error.json_location??(match?{offset:match[1],line:match[2],column:match[3]}:lineOnly?{line:lineOnly[1],column:lineOnly[2]}:{});
  return Object.fromEntries(['offset','line','column'].filter(key=>candidates[key]!==undefined&&Number.isSafeInteger(Number(candidates[key]))&&Number(candidates[key])>=0).map(key=>[key,Number(candidates[key])]));
}

// Only remove an enclosing Markdown json fence; never repair model content.
export function parseStructuredResponse(response) {
  if(typeof response!=='string')throw new Error('structured response must be text');
  const text=response.trim();
  const fenced=/^```json[ \t]*\r?\n([\s\S]*?)\r?\n```$/.exec(text);
  let data;
  try{data=JSON.parse(fenced?fenced[1]:text);}catch(error){const safe=new SyntaxError('structured response must be a JSON object or one json code block');safe.json_location=jsonParseLocation(error);throw safe;}
  if(data===null||typeof data!=='object'||Array.isArray(data))throw new Error('structured response must be a JSON object');
  return data;
}
