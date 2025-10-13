using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Threading.Tasks;
using Northwind.Application.Orders.Queries.GetOrderDetails;

namespace Northwind.WebUI.Controllers
{
    [Authorize]
    public class OrderDetailsController : BaseController
    {
        [HttpGet("{id}")]
        [AllowAnonymous]
        public async Task<ActionResult<OrderDetailsVm>> GetOrderDetails(int id)
        {
            var query = new GetOrderDetailsQuery { OrderId = id };
            var vm = await Mediator.Send(query);

            return Ok(vm);
        }
    }
}