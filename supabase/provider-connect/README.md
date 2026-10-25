# Candidate provider custody

Candidate SQL is deliberately outside migrations. No relay or Webull dependency. Installation is atomic; only service_role can execute public.crier_oauth_flow(text,uuid,text,jsonb). Neither client roles nor service_role can directly access the RLS private tables/schema. The trusted gateway authenticates customer ownership independently. READ COMMITTED is required.

RPC parameters are p_action text, p_owner uuid, p_flow text, p_input jsonb. Semantic rejects return {ok:false}, preserving expiry scrubs. Successful flow actions return {ok:true,flow:row}. Input keys/types are exact; unknown keys reject.

| Action | p_flow | p_input |
|---|---|---|
| begin | server-chosen ID | provider,purpose,environment,challenge,ticket_hash,state_hash,state_ciphertext |
| launch | ID or null | ticket_hash,binding_hash |
| claim | ID or null | provider,state_hash,binding_hash |
| complete | ID | grant_ciphertext |
| status | ID | {} |
| redeem | ID | proof_hash |
| cancel | ID | proof_hash |
| fail | ID | {} |
| cleanup | null | limit: integer 1..1000 |
| csrf_claim | null | hash,expires_at: integer epoch ms |

Owner is required except cleanup/csrf_claim, which require null owner and flow. cleanup returns {ok:true,count,csrf_count}; each deletion count is bounded by limit. csrf_claim returns {ok:true,claimed:boolean}. CSRF deadline must be future and <= DB now +360000 ms. Effective expiry is clamped to DB now +300000 ms, but tombstones retain the submitted deadline to close replay gaps after cleanup during clock skew. Browser CSRF protection combines a host-only cookie, exact Origin, matching hidden proof and durable one-use claims; deadlines are not signatures.

Flow fields: flow_id,owner_id,provider,purpose,environment,challenge,stage,created_at,expires_at,ready_until,ticket_hash,state_hash,binding_hash,state_ciphertext,grant_ciphertext. Clock fields are bigint epoch ms; ready_until nullable. Hashes are 64 lowercase hex or null. Flow IDs are 43 ASCII base64url characters. Provider alpaca/discord; purpose alerts/trade (Discord alerts only); environment paper/live. Gateway must allowlist public status metadata, never forward internal rows directly.

Envelope is exactly {version:1,key_id,nonce,ciphertext}. key_id is 1..64 ASCII base64url, nonce16 ASCII base64url (12 bytes), ciphertext22..90000 ASCII base64url with length modulo4 !=1. No padding. Gateway validates/decrypts with external AES-GCM key and context-bound AAD. SQL cannot prove encryption or entropy.

Owner locks enforce eight active flows per owner, four per owner/challenge. Row locks protect one-use transitions. Clock is sampled after lock acquisition. Fixed TTL300000ms; ready <=60000ms and original deadline. launch/redeem return previous ciphertext after atomically removing stored ciphertext. Wrong owner cannot scrub; expiry clears secrets and preserves terminal metadata until TTL/cleanup. fail only accepts exchanging. Exchanging remains uncertain; no retry. cleanup uses SKIP LOCKED.

provider_flows.sql runs in PGlite/PostgreSQL. integration/provider_flows_concurrency.sql requires real PostgreSQL/dblink plus crier.test_dsn. All fixtures are synthetic.

