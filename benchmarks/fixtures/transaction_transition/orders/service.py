def checkout(order, repository, charge):
    if order.state != 'pending': raise ValueError('invalid transition')
    repository.stock -= 1
    charge(order.id)
    order.state = 'paid'
    repository.save(order)
