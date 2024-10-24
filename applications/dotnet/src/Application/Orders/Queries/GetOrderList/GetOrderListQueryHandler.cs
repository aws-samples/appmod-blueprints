using System.Threading;
using System.Threading.Tasks;
using AutoMapper;
using AutoMapper.QueryableExtensions;
using MediatR;
using Microsoft.EntityFrameworkCore;
using Northwind.Application.Common.Exceptions;
using Northwind.Application.Common.Interfaces;

﻿namespace Northwind.Application.Orders.Queries.GetOrderList
{
    public class GetOrderListQueryHandler :  IRequestHandler<GetOrderListQuery, OrdersListVm>
    {
        private readonly INorthwindDbContext _context;
        private readonly IMapper _mapper;

        public GetOrderListQueryHandler(INorthwindDbContext context, IMapper mapper)
        {
            _context = context;
            _mapper = mapper;
        }

        public async Task<OrdersListVm> Handle(GetOrderListQuery request, CancellationToken cancellationToken)
        {
            var orders = await _context.Orders
                .ProjectTo<OrderDto>(_mapper.ConfigurationProvider)
                .ToListAsync(cancellationToken);

            var vm = new OrdersListVm
            {
                Orders = orders
            };

            return vm;
        }
    }
}

// Tests
// TODO: Add test cases for GetOrderDetailsQueryHandler
