// Only remove an enclosing Markdown json fence; never repair model content.
export function parseStructuredResponse(response) {
  if(typeof response!=='string')throw new Error('structured response must be text');
  const text=response.trim();
  const fenced=/^```json[ \t]*\r?\n([\s\S]*?)\r?\n```$/.exec(text);
  let data;
  try{data=JSON.parse(fenced?fenced[1]:text);}catch{throw new Error('structured response must be a JSON object or one json code block');}
  if(data===null||typeof data!=='object'||Array.isArray(data))throw new Error('structured response must be a JSON object');
  return data;
}
