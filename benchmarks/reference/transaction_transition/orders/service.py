def checkout(order, repository, charge):
    if order.state != 'pending': raise ValueError('invalid transition')
    if repository.stock < 1: raise ValueError('out of stock')
    old_stock, old_state = repository.stock, order.state
    try:
        charge(order.id)
        repository.stock -= 1
        order.state = 'paid'
        repository.save(order)
    except BaseException:
        repository.stock, order.state = old_stock, old_state
        repository.states.pop(order.id, None)
        raise
