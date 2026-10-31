"""Read-only recovery guidance. No execution or block-clearing authority."""
def recovery_report(bank,scope):
    with bank.locked(scope):
        account=bank.account(scope)
        orders=bank.orders(scope)
        ids=bank.active(scope)
    unknown=sum(row['status']=='unknown' for row in orders)
    blocked=account['blocked']
    explanation=('An order outcome is unknown. Preserve reservations and do not resubmit; look up the original client-order ID with the broker.' if unknown else
        'Broker evidence needs reconciliation. Compare account positions, order identities and cumulative fills without reassigning host ownership.' if blocked else
        'No local conflict recorded. This is not fresh broker verification; verify the account before resuming.')
    return dict(state='needs_reconciliation' if blocked or unknown else 'no_local_conflict',
        unknown_orders=unknown,reason=blocked,broker_checked=False,can_clear=False,
        explanation=explanation,ids=ids,
        steps=['Pause new entries across all routes using this account.',
               'Confirm broker account and paper/live environment.',
               'Compare broker positions and orders with retained trade IDs.',
               'Preserve the complete private profile; never delete IDs to bypass a block.'])
