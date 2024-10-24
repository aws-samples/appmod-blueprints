using AutoMapper;
using Northwind.Application.Common.Mappings;
using Northwind.Application.Customers.Queries.GetCustomersList;
using Northwind.Domain.Entities;
using System;
using System.Collections.Generic;

namespace Northwind.Application.Orders.Queries.GetOrderList
{
    public class OrdersListVm 
    {
        public IList<OrderDto> Orders { get; set; }
    }


}

