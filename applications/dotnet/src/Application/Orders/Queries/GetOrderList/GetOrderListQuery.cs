using MediatR;

﻿namespace Northwind.Application.Orders.Queries.GetOrderList
{
    public class GetOrderListQuery : IRequest<OrdersListVm>
    {
    }
}
