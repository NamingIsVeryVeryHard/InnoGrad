export class PortraitError extends Error {
  constructor(code,message,details={}) { super(message); this.name='PortraitError'; this.code=code; Object.assign(this,details); }
}
export const failure=(code,message,details)=>new PortraitError(code,message,details);
export function requestFailure(error,signal) {
  if(signal?.aborted)return failure('ABORTED','request cancelled');
  if(error?.name==='TimeoutError'||error?.name==='AbortError')return failure('REMOTE_TIMEOUT','remote request timed out');
  const networkCode=error?.cause?.code;
  return failure('REMOTE_NETWORK','remote network request failed',typeof networkCode==='string'&&/^[A-Z_0-9]+$/.test(networkCode)?{network_code:networkCode}:{});
}
