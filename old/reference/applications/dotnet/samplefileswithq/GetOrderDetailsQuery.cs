using MediatR;

namespace Northwind.Application.Orders.Queries.GetOrderDetails
{
    public class GetOrderDetailsQuery : IRequest<OrderDetailsVm>
    {
        public int OrderId { get; set; }
    }
}