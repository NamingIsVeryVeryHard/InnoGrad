import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {parseEnv} from 'node:util';
import {failure} from './errors.mjs';
// Explicit project file only. Existing process values take precedence; no ancestor or home search.
export async function loadProjectEnv({env=process.env,path=env.PORTRAIT_ENV_FILE??resolve(process.cwd(),'.env')}={}) {
  let text;try{text=await readFile(path,'utf8');}catch(e){if(e.code==='ENOENT')return {...env};throw failure('CONFIGURATION','project environment file cannot be read');}
  let parsed;try{parsed=parseEnv(text);}catch{throw failure('CONFIGURATION','project environment file is invalid');}
  return {...parsed,...env};
}
