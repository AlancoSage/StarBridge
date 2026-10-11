// Browser-side integration: only public endpoints, never embed a backend API key.
// Configure this website's origin in Myrinbot → Members → Registered accounts.
export function createStarBridgeRegistration(baseUrl) {
  const clean = baseUrl.replace(/\/+$/, '');
  const base = clean.endsWith('/api/v1') ? clean : clean + '/api/v1';
  async function request(path, body, accessToken) {
    const response = await fetch(base + path, {
      method: body ? 'POST' : 'GET',
      headers: {
        ...(body ? {'Content-Type': 'application/json'} : {}),
        ...(accessToken ? {'Authorization': 'Bearer ' + accessToken} : {}),
      },
      ...(body ? {body: JSON.stringify(body)} : {}),
      cache: 'no-store',
      signal: AbortSignal.timeout(45000),
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || '请求失败');
      error.code = data.code; error.status = response.status; throw error;
    }
    return data;
  }
  return {
    communityInfo: () => request('/community/info'),
    servers: () => request('/servers'),
    players: ({q = '', page = 1, pageSize = 24} = {}) => request('/players?' + new URLSearchParams({q,page:String(page),page_size:String(pageSize)})),
    player: uuid => request('/players/' + encodeURIComponent(uuid)),
    login: (player,password) => request('/account/login', {player,password}),
    logout: accessToken => request('/account/logout', {}, accessToken),
    profile: accessToken => request('/me/profile', null, accessToken),
    services: accessToken => request('/me/services', null, accessToken),
    tickets: (accessToken,page=1) => request('/me/tickets?page='+encodeURIComponent(page),null,accessToken),
    ticket: (accessToken,id) => request('/me/tickets/'+encodeURIComponent(id),null,accessToken),
    createTicket: (accessToken,data) => request('/me/tickets',data,accessToken),
    replyTicket: (accessToken,id,body,revision) => request('/me/tickets/'+encodeURIComponent(id)+'/reply',{body,revision},accessToken),
    bind: (accessToken,server,code) => request('/me/bind',{server,code},accessToken),
    unbind: (accessToken,server) => request('/me/unbind',{server},accessToken),
    applyWhitelist: (accessToken,server,reason='') => request('/me/whitelist',{server,reason},accessToken),
    info: () => request('/registration/info'),
    apply: (player, email) => request('/registration/request', {player, email}),
    resend: challengeId => request('/registration/resend', {challenge_id: challengeId}),
    verify: (challengeId, code, password) => request('/registration/verify', {challenge_id: challengeId, code, ...(password!==undefined?{password}:{})}),
    requestPassword: (player,email) => request('/account/password/request', {player,email}),
    setPassword: (challengeId,code,password) => request('/account/password/verify', {challenge_id:challengeId,code,password}),
    account: accessToken => request('/account', null, accessToken),
  };
}

export const createStarBridgeClient = createStarBridgeRegistration;

// Recommended names for new integrations.
export const createMyrinbotRegistration = createStarBridgeRegistration;
export const createMyrinbotClient = createStarBridgeClient;

// Example:
// const client = createMyrinbotRegistration('https://bridge.example.com');
// const application = await client.apply('Steve', '123456789@qq.com');
// const result = await client.verify(application.challenge_id, enteredCode, chosenPassword);
// const me = await client.account(result.access_token);
// Send the short-lived token to your own backend for validation, then create
// your own website session. Account ID is not a Minecraft player UUID.

// Compatibility aliases for existing integrations.
export const createAetherBotRegistration = createStarBridgeRegistration;
export const createAetherBotClient = createStarBridgeClient;
