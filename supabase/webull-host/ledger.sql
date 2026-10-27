-- Candidate only: outside deployment migrations until provider integration acceptance.
begin;
create schema if not exists webull_host_private;
revoke all on schema webull_host_private from public, anon, authenticated;
create table if not exists webull_host_private.orders (
 owner uuid not null,
 client_order_id text not null check(client_order_id ~ '^([a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$'),
 intent jsonb not null check(jsonb_typeof(intent)='object'),
 fingerprint text not null check(length(fingerprint) between 1 and 4096),
 receipt jsonb not null,
 revision integer not null default 1 check(revision>0),
 cancel_claimed boolean not null default false,
 cancel_pending boolean not null default false,
 cancel_revision integer,
 cancel_started_at timestamptz,
 created_at timestamptz not null default clock_timestamp(),
 updated_at timestamptz not null default clock_timestamp(),
 primary key(owner,client_order_id)
);
alter table webull_host_private.orders enable row level security;
revoke all on webull_host_private.orders from public,anon,authenticated;
create index if not exists webull_host_inventory_scope on webull_host_private.orders
 (owner,(intent->>'environment'),(intent->>'account_id'),(intent->>'asset'),(intent->>'symbol'));
create table if not exists webull_host_private.quantity_scopes (
 owner uuid not null, environment text not null check(environment in ('sandbox','production')),
 account_id text not null check(length(account_id) between 1 and 200),
 asset text not null check(asset in ('stock','option')), symbol text not null check(length(symbol) between 1 and 21),
 blocked boolean not null default false,
 primary key(owner,environment,account_id,asset,symbol)
);
alter table webull_host_private.quantity_scopes enable row level security;
revoke all on webull_host_private.quantity_scopes from public,anon,authenticated,service_role;
create or replace function webull_host_private.lock_quantity(p_owner uuid,p_order jsonb)
returns void language plpgsql set search_path='' as $$
begin
 if current_setting('transaction_isolation')<>'read committed' then raise exception 'READ COMMITTED required'; end if;
 insert into webull_host_private.quantity_scopes(owner,environment,account_id,asset,symbol)
 values(p_owner,p_order->>'environment',p_order->>'account_id',p_order->>'asset',p_order->>'symbol') on conflict do nothing;
 perform 1 from webull_host_private.quantity_scopes where owner=p_owner and environment=p_order->>'environment'
 and account_id=p_order->>'account_id' and asset=p_order->>'asset' and symbol=p_order->>'symbol' for update;
end $$;
revoke all on function webull_host_private.lock_quantity(uuid,jsonb) from public,anon,authenticated,service_role;
-- Only the service role may call these RPCs. It supplies the Auth-verified owner.
create or replace function public.webull_host_reserve(p_owner uuid,p_order jsonb,p_fingerprint text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare inserted integer; found_row webull_host_private.orders; owned numeric; denied text;
begin
 if p_owner is null or p_order is null or p_fingerprint is null
 or jsonb_typeof(p_order)<>'object' or not (p_order ?& array['client_order_id','account_id','environment','asset','symbol','quantity','limit_price','side'])
 or p_order->>'environment' not in ('sandbox','production')
 or p_order->>'side' not in ('buy','sell') or p_order->>'asset' not in ('stock','option')
 or jsonb_typeof(p_order->'quantity') is distinct from 'number'
 or (p_order->>'quantity')::numeric not between 1 and 1000000
 or (p_order->>'quantity')::numeric<>trunc((p_order->>'quantity')::numeric)
 then raise exception 'Invalid Webull ledger intent'; end if;
 perform webull_host_private.lock_quantity(p_owner,p_order);
 -- Idempotency precedes quantity checks: an uncertain dispatch is never reserved twice.
 select * into found_row from webull_host_private.orders where owner=p_owner and client_order_id=p_order->>'client_order_id';
 if not found then
   if exists(select 1 from webull_host_private.quantity_scopes where owner=p_owner and environment=p_order->>'environment'
    and account_id=p_order->>'account_id' and asset=p_order->>'asset' and symbol=p_order->>'symbol' and blocked) then
     denied='source_inventory_reconciliation_required';
   elsif p_order->>'side'='sell' then
     select coalesce(sum(case when intent->>'side'='buy' then (receipt->>'filled_quantity')::numeric
       when receipt->>'status' in ('filled','canceled','rejected') then -(receipt->>'filled_quantity')::numeric
       else -(intent->>'quantity')::numeric end),0) into owned
     from webull_host_private.orders where owner=p_owner and intent->>'environment'=p_order->>'environment'
       and intent->>'account_id'=p_order->>'account_id' and intent->>'asset'=p_order->>'asset' and intent->>'symbol'=p_order->>'symbol';
     if owned<(p_order->>'quantity')::numeric then denied='insufficient_tracked_long_position'; end if;
   end if;
   if denied is not null then return jsonb_build_object('created',false,'row',null,'reason',denied); end if;
 end if;
 insert into webull_host_private.orders(owner,client_order_id,intent,fingerprint,receipt)
 values(p_owner,p_order->>'client_order_id',p_order,p_fingerprint,jsonb_build_object('client_order_id',p_order->>'client_order_id','status','unknown','filled_quantity',0))
 on conflict(owner,client_order_id) do nothing;
 get diagnostics inserted=row_count;
 select * into strict found_row from webull_host_private.orders where owner=p_owner and client_order_id=p_order->>'client_order_id';
 return jsonb_build_object('created',inserted=1,'row',jsonb_build_object('owner',found_row.owner,'order',found_row.intent,'fingerprint',found_row.fingerprint,'receipt',found_row.receipt,'revision',found_row.revision,'cancel_claimed',found_row.cancel_claimed,'cancel_pending',found_row.cancel_pending,'cancel_revision',found_row.cancel_revision));
end $$;
create or replace function public.webull_host_read(p_owner uuid,p_id text)
returns jsonb language sql security definer set search_path = '' as $$
 select jsonb_build_object('owner',owner,'order',intent,'fingerprint',fingerprint,'receipt',receipt,'revision',revision,'cancel_claimed',cancel_claimed,'cancel_pending',cancel_pending,'cancel_revision',cancel_revision)
 from webull_host_private.orders where owner=p_owner and client_order_id=p_id
$$;
create or replace function public.webull_host_claim_cancel(p_owner uuid,p_id text,p_revision integer)
returns jsonb language sql security definer set search_path = '' as $$
 update webull_host_private.orders set cancel_claimed=true,cancel_pending=true,cancel_revision=revision+1,cancel_started_at=clock_timestamp(),revision=revision+1,updated_at=clock_timestamp()
 where owner=p_owner and client_order_id=p_id and revision=p_revision and not cancel_claimed
 and receipt->>'status' in ('accepted','partially_filled')
 returning jsonb_build_object('owner',owner,'order',intent,'fingerprint',fingerprint,'receipt',receipt,'revision',revision,'cancel_claimed',cancel_claimed,'cancel_pending',cancel_pending,'cancel_revision',cancel_revision)
$$;
create or replace function public.webull_host_settle_cancel(p_owner uuid,p_id text,p_cancel_revision integer)
returns boolean language plpgsql security definer set search_path = '' as $$
declare changed integer;
begin
 update webull_host_private.orders set cancel_pending=false,revision=revision+1,updated_at=clock_timestamp()
 where owner=p_owner and client_order_id=p_id and cancel_revision=p_cancel_revision and cancel_pending;
 get diagnostics changed=row_count; return changed=1;
end $$;
create or replace function public.webull_host_save(p_owner uuid,p_id text,p_revision integer,p_receipt jsonb,p_action text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare changed integer; q numeric; status text; prior webull_host_private.orders;
begin
 q=(p_receipt->>'filled_quantity')::numeric; status=p_receipt->>'status';
 if p_receipt is null or p_receipt->>'client_order_id' is distinct from p_id
 or status is null or status not in ('accepted','partially_filled','filled','canceled','rejected','unknown')
 or jsonb_typeof(p_receipt->'filled_quantity') is distinct from 'number' or q<0 or q<>trunc(q)
 or (status in ('accepted','unknown','rejected') and q<>0)
 or p_action is null or p_action not in ('submit','lookup','cancel') then raise exception 'Invalid Webull ledger receipt'; end if;
 select * into prior from webull_host_private.orders where owner=p_owner and client_order_id=p_id;
 if not found then return false; end if;
 perform webull_host_private.lock_quantity(p_owner,prior.intent);
 select * into prior from webull_host_private.orders where owner=p_owner and client_order_id=p_id for update;
 if prior.revision<>p_revision then return false; end if;
 if p_action='lookup' and (
   (prior.receipt->>'status' in ('filled','canceled','rejected') and
    (status<>prior.receipt->>'status' or q<>(prior.receipt->>'filled_quantity')::numeric))
   or q<(prior.receipt->>'filled_quantity')::numeric
   or (prior.receipt->>'broker_order_id' is not null and p_receipt->>'broker_order_id' is not null
    and prior.receipt->>'broker_order_id'<>p_receipt->>'broker_order_id')) then
   update webull_host_private.quantity_scopes set blocked=true where owner=p_owner and environment=prior.intent->>'environment'
    and account_id=prior.intent->>'account_id' and asset=prior.intent->>'asset' and symbol=prior.intent->>'symbol';
   return false;
 end if;
 update webull_host_private.orders set receipt=p_receipt,revision=revision+1,updated_at=clock_timestamp(),
 cancel_pending=case when p_action='cancel' or (p_action='lookup' and cancel_started_at<clock_timestamp()-interval '60 seconds') then false else cancel_pending end,
 cancel_claimed=case when p_action='lookup' and status in ('accepted','partially_filled') and (not cancel_pending or cancel_started_at<clock_timestamp()-interval '60 seconds') then false else cancel_claimed end
 where owner=p_owner and client_order_id=p_id and revision=p_revision
 and q>=(receipt->>'filled_quantity')::numeric and q<=(intent->>'quantity')::numeric
 and (status<>'filled' or q=(intent->>'quantity')::numeric)
 and (status<>'partially_filled' or (q>0 and q<(intent->>'quantity')::numeric))
 and (receipt->>'status' not in ('filled','canceled','rejected') or status=receipt->>'status')
 and (receipt->>'broker_order_id' is null or p_receipt->>'broker_order_id'=receipt->>'broker_order_id');
 get diagnostics changed=row_count; return changed=1;
end $$;
create or replace function public.webull_host_block_inventory(p_owner uuid,p_id text)
returns boolean language plpgsql security definer set search_path='' as $$
declare prior webull_host_private.orders;
begin
 select * into prior from webull_host_private.orders where owner=p_owner and client_order_id=p_id;
 if not found then return false; end if;
 perform webull_host_private.lock_quantity(p_owner,prior.intent);
 update webull_host_private.quantity_scopes set blocked=true where owner=p_owner and environment=prior.intent->>'environment'
 and account_id=prior.intent->>'account_id' and asset=prior.intent->>'asset' and symbol=prior.intent->>'symbol';
 return true;
end $$;
revoke all on function public.webull_host_block_inventory(uuid,text) from public,anon,authenticated;
grant execute on function public.webull_host_block_inventory(uuid,text) to service_role;
revoke all on function public.webull_host_reserve(uuid,jsonb,text) from public,anon,authenticated;
revoke all on function public.webull_host_read(uuid,text) from public,anon,authenticated;
revoke all on function public.webull_host_claim_cancel(uuid,text,integer) from public,anon,authenticated;
revoke all on function public.webull_host_settle_cancel(uuid,text,integer) from public,anon,authenticated;
revoke all on function public.webull_host_save(uuid,text,integer,jsonb,text) from public,anon,authenticated;
grant execute on function public.webull_host_reserve(uuid,jsonb,text) to service_role;
grant execute on function public.webull_host_read(uuid,text) to service_role;
grant execute on function public.webull_host_claim_cancel(uuid,text,integer) to service_role;
grant execute on function public.webull_host_settle_cancel(uuid,text,integer) to service_role;
grant execute on function public.webull_host_save(uuid,text,integer,jsonb,text) to service_role;
commit;
