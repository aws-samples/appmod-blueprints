using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Northwind.Application.Orders.Queries.GetOrderList;
using System.Threading.Tasks;

namespace Northwind.WebUI.Controllers
{
    [Authorize]
    public class OrdersController : BaseController
    {
        [HttpGet]
        [AllowAnonymous]
        public async Task<ActionResult<OrdersListVm>> GetAll()
        {
            var vm = await Mediator.Send(new GetOrderListQuery());

            return base.Ok(vm);
        }
    }
}