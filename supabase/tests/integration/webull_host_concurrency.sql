-- Real PostgreSQL test DB only. No provider or external network calls.
create extension if not exists dblink with schema extensions;
do $$
declare a boolean;b boolean;q text;o text='00000000-0000-4000-8000-000000000026';
begin
 if nullif(current_setting('crier.test_dsn',true),'') is null then raise exception 'Isolated test DSN required';end if;
 perform extensions.dblink_connect('wh_a',current_setting('crier.test_dsn'));
 perform extensions.dblink_connect('wh_b',current_setting('crier.test_dsn'));
 perform v from extensions.dblink('wh_a',format('select public.webull_host_browser_issue(%L,''sandbox'',%L) is not null',o,repeat('d',64))) as t(v boolean);
 q=format('select public.webull_host_browser_launch(%L) is not null',repeat('d',64));
 perform extensions.dblink_exec('wh_a','begin');
 select v into a from extensions.dblink('wh_a',q) as t(v boolean);
 perform extensions.dblink_send_query('wh_b',q);perform pg_sleep(0.1);
 assert extensions.dblink_is_busy('wh_b')=1,'Concurrent launch must wait for winner';
 perform extensions.dblink_exec('wh_a','commit');
 select v into b from extensions.dblink_get_result('wh_b') as t(v boolean);
 assert a and not b,'Exactly one launch may win';
 perform v from extensions.dblink_get_result('wh_b') as t(v boolean);

 q=format('select public.webull_host_admit(%L,''http'',1)',o);
 perform extensions.dblink_exec('wh_a','begin');
 select v into a from extensions.dblink('wh_a',q) as t(v boolean);
 perform extensions.dblink_send_query('wh_b',q);perform pg_sleep(0.1);
 assert extensions.dblink_is_busy('wh_b')=1,'Admission must serialize across workers';
 perform extensions.dblink_exec('wh_a','commit');
 select v into b from extensions.dblink_get_result('wh_b') as t(v boolean);
 assert a and not b,'Concurrent requests must share quota';
 perform v from extensions.dblink_get_result('wh_b') as t(v boolean);

 q=format('select (public.webull_host_reserve(%L,%L::jsonb,''fixture'')->>''created'')::boolean',o,jsonb_build_object('client_order_id',repeat('d',32),'account_id','fixture','environment','sandbox','asset','stock','symbol','SPY','quantity',1,'limit_price','1','side','buy')::text);
 perform extensions.dblink_exec('wh_a','begin');
 select v into a from extensions.dblink('wh_a',q) as t(v boolean);
 perform extensions.dblink_send_query('wh_b',q);perform pg_sleep(0.1);
 assert extensions.dblink_is_busy('wh_b')=1,'Concurrent order reservation must wait';
 perform extensions.dblink_exec('wh_a','commit');
 select v into b from extensions.dblink_get_result('wh_b') as t(v boolean);
 assert a and not b,'Exactly one source order dispatch may be reserved';
 perform v from extensions.dblink_get_result('wh_b') as t(v boolean);

 -- Distinct sell IDs must contend on the quantity scope, not merely the order PK.
 q=format('select public.webull_host_save(%L,%L,1,%L::jsonb,''lookup'')',o,repeat('d',32),jsonb_build_object('client_order_id',repeat('d',32),'status','filled','filled_quantity',1,'broker_order_id','fixture-buy')::text);
 select v into a from extensions.dblink('wh_a',q) as t(v boolean);
 assert a,'Buy fills must be committed before allocating source inventory';
 q=format('select (public.webull_host_reserve(%L,%L::jsonb,''sell-a'')->>''created'')::boolean',o,jsonb_build_object('client_order_id',repeat('e',32),'account_id','fixture','environment','sandbox','asset','stock','symbol','SPY','quantity',1,'limit_price','1','side','sell')::text);
 perform extensions.dblink_exec('wh_a','begin');
 select v into a from extensions.dblink('wh_a',q) as t(v boolean);
 q=format('select (public.webull_host_reserve(%L,%L::jsonb,''sell-b'')->>''created'')::boolean',o,jsonb_build_object('client_order_id',repeat('f',32),'account_id','fixture','environment','sandbox','asset','stock','symbol','SPY','quantity',1,'limit_price','1','side','sell')::text);
 perform extensions.dblink_send_query('wh_b',q);perform pg_sleep(0.1);
 assert extensions.dblink_is_busy('wh_b')=1,'Different sell IDs must serialize against shared owned quantity';
 perform extensions.dblink_exec('wh_a','commit');
 select v into b from extensions.dblink_get_result('wh_b') as t(v boolean);
 assert a and not b,'Only one competing sell may consume one owned share';
 perform v from extensions.dblink_get_result('wh_b') as t(v boolean);
 assert not has_function_privilege('anon','public.webull_host_browser_launch(text)','execute');
 assert not has_function_privilege('authenticated','public.webull_host_admit(uuid,text,integer)','execute');
 assert not has_function_privilege('authenticated','public.webull_host_block_inventory(uuid,text)','execute');
 perform extensions.dblink_exec('wh_a',format('delete from webull_host_private.browser_flows where owner=%L;delete from webull_host_private.request_events where owner=%L;delete from webull_host_private.request_windows where owner=%L;delete from webull_host_private.orders where owner=%L;delete from webull_host_private.quantity_scopes where owner=%L;',o,o,o,o,o));
 perform extensions.dblink_disconnect('wh_a');perform extensions.dblink_disconnect('wh_b');
end $$;
