-- Candidate service-only browser state and admission; not a deployed migration.
begin;
create schema if not exists webull_host_private;
revoke all on schema webull_host_private from public,anon,authenticated;
create table if not exists webull_host_private.browser_flows(
 id uuid primary key default gen_random_uuid(),owner uuid not null,
 environment text not null check(environment in ('sandbox','production')),
 ticket_hash text not null unique check(ticket_hash ~ '^[a-f0-9]{64}$'),
 state_hash text unique check(state_hash ~ '^[a-f0-9]{64}$'),
 phase text not null default 'created' check(phase in ('created','launching','pending','complete','revoked')),
 expires_at timestamptz not null default clock_timestamp()+interval '5 minutes'
);
create index if not exists webull_browser_owner on webull_host_private.browser_flows(owner,environment,expires_at);
alter table webull_host_private.browser_flows enable row level security;
revoke all on webull_host_private.browser_flows from public,anon,authenticated;
create table if not exists webull_host_private.request_windows(
 owner uuid not null,scope text not null check(scope in ('http','webull')),
 window_start timestamptz not null,used integer not null check(used>0),primary key(owner,scope)
);
alter table webull_host_private.request_windows enable row level security;
revoke all on webull_host_private.request_windows from public,anon,authenticated;
create table if not exists webull_host_private.request_events(
 id bigint generated always as identity primary key,owner uuid not null,
 scope text not null check(scope in ('http','webull')),observed_at timestamptz not null
);
create index if not exists webull_request_scope on webull_host_private.request_events(owner,scope,observed_at);
alter table webull_host_private.request_events enable row level security;
revoke all on webull_host_private.request_events from public,anon,authenticated;
create or replace function webull_host_private.browser_json(f webull_host_private.browser_flows)
returns jsonb language sql immutable set search_path='' as $$
 select jsonb_build_object('id',f.id,'owner',f.owner,'environment',f.environment,'expires_at_ms',floor(extract(epoch from f.expires_at)*1000),'state_hash',f.state_hash)
$$;
revoke all on function webull_host_private.browser_json(webull_host_private.browser_flows) from public,anon,authenticated;
create or replace function public.webull_host_browser_issue(p_owner uuid,p_environment text,p_ticket_hash text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare f webull_host_private.browser_flows;
begin
 if p_owner is null or p_environment is null or p_environment not in ('sandbox','production') or p_ticket_hash is null or p_ticket_hash !~ '^[a-f0-9]{64}$' then raise exception 'Invalid browser flow';end if;
 delete from webull_host_private.browser_flows where owner=p_owner and environment=p_environment and expires_at<clock_timestamp();
 insert into webull_host_private.browser_flows(owner,environment,ticket_hash) values(p_owner,p_environment,p_ticket_hash) returning * into f;
 return webull_host_private.browser_json(f);
end $$;
create or replace function public.webull_host_browser_launch(p_ticket_hash text)
returns jsonb language sql security definer set search_path='' as $$
 update webull_host_private.browser_flows set phase='launching' where ticket_hash=p_ticket_hash and phase='created' and expires_at>clock_timestamp() returning webull_host_private.browser_json(browser_flows.*)
$$;
create or replace function public.webull_host_browser_attach(p_id uuid,p_state_hash text,p_expires_at_ms bigint)
returns boolean language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 if p_state_hash is null or p_state_hash !~ '^[a-f0-9]{64}$' or p_expires_at_ms is null or p_expires_at_ms<=extract(epoch from clock_timestamp())*1000 or p_expires_at_ms>extract(epoch from clock_timestamp()+interval '5 minutes 1 second')*1000 then raise exception 'Invalid browser state';end if;
 update webull_host_private.browser_flows set phase='pending',state_hash=p_state_hash,expires_at=to_timestamp(p_expires_at_ms/1000.0) where id=p_id and phase='launching' and expires_at>clock_timestamp();
 get diagnostics n=row_count;return n=1;
end $$;
create or replace function public.webull_host_browser_resolve(p_state_hash text)
returns jsonb language sql security definer set search_path='' as $$
 select webull_host_private.browser_json(browser_flows.*) from webull_host_private.browser_flows where state_hash=p_state_hash and phase='pending' and expires_at>clock_timestamp()
$$;
create or replace function public.webull_host_browser_complete(p_id uuid)
returns boolean language plpgsql security definer set search_path='' as $$
declare n integer;begin
 update webull_host_private.browser_flows set phase='complete' where id=p_id and phase='pending';get diagnostics n=row_count;return n=1;
end $$;
create or replace function public.webull_host_browser_invalidate(p_owner uuid,p_environment text)
returns boolean language plpgsql security definer set search_path='' as $$
begin
 update webull_host_private.browser_flows set phase='revoked' where owner=p_owner and environment=p_environment and phase in ('created','launching','pending');return true;
end $$;
create or replace function public.webull_host_admit(p_owner uuid,p_scope text,p_limit integer)
returns boolean language plpgsql security definer set search_path='' as $$
declare b timestamptz;n integer;
begin
 if p_owner is null or p_scope is null or p_scope not in ('http','webull') or p_limit is null or p_limit<1 or p_limit>80 then raise exception 'Invalid admission';end if;
 -- A durable per-customer/scope mutex serializes admission across Edge workers.
 insert into webull_host_private.request_windows(owner,scope,window_start,used) values(p_owner,p_scope,clock_timestamp(),1) on conflict(owner,scope) do nothing;
 perform 1 from webull_host_private.request_windows where owner=p_owner and scope=p_scope for update;
 b=clock_timestamp();
 delete from webull_host_private.request_events where owner=p_owner and scope=p_scope and observed_at<=b-interval '60 seconds';
 select count(*) into n from webull_host_private.request_events where owner=p_owner and scope=p_scope;
 if n>=p_limit then return false;end if;
 insert into webull_host_private.request_events(owner,scope,observed_at) values(p_owner,p_scope,b);
 update webull_host_private.request_windows set window_start=b,used=n+1 where owner=p_owner and scope=p_scope;
 return true;
end $$;
revoke all on function public.webull_host_browser_issue(uuid,text,text) from public,anon,authenticated;
revoke all on function public.webull_host_browser_launch(text) from public,anon,authenticated;
revoke all on function public.webull_host_browser_attach(uuid,text,bigint) from public,anon,authenticated;
revoke all on function public.webull_host_browser_resolve(text) from public,anon,authenticated;
revoke all on function public.webull_host_browser_complete(uuid) from public,anon,authenticated;
revoke all on function public.webull_host_browser_invalidate(uuid,text) from public,anon,authenticated;
revoke all on function public.webull_host_admit(uuid,text,integer) from public,anon,authenticated;
grant execute on function public.webull_host_browser_issue(uuid,text,text) to service_role;
grant execute on function public.webull_host_browser_launch(text) to service_role;
grant execute on function public.webull_host_browser_attach(uuid,text,bigint) to service_role;
grant execute on function public.webull_host_browser_resolve(text) to service_role;
grant execute on function public.webull_host_browser_complete(uuid) to service_role;
grant execute on function public.webull_host_browser_invalidate(uuid,text) to service_role;
grant execute on function public.webull_host_admit(uuid,text,integer) to service_role;
commit;
