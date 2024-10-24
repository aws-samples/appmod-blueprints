using AutoMapper;
using Northwind.Application.Common.Mappings;
using Northwind.Application.Customers.Queries.GetCustomersList;
using Northwind.Domain.Entities;

namespace Northwind.Application.Orders.Queries.GetOrderList
{
    public class OrderDto : IMapFrom<OrderDetail>
    {
        public int OrderId { get; set; }
        public string CustomerId { get; set; }
        public string ShipName { get; set; }
        public string ShipCity { get; set; }

        public void Mapping(Profile profile)
        {
            profile.CreateMap<Order, OrderDto>()
                .ForMember(d => d.OrderId, opt => opt.MapFrom(s => s.OrderId))
                .ForMember(d => d.CustomerId, opt => opt.MapFrom(s => s.CustomerId))
                .ForMember(d => d.ShipName, opt => opt.MapFrom(s => s.ShipName))
                .ForMember(d => d.ShipCity, opt => opt.MapFrom(s => s.ShipCity));                
        }
    }
}
