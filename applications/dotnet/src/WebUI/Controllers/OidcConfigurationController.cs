using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace Northwind.WebUI.Controllers
{
    [ApiExplorerSettings(IgnoreApi = true)]
    public class OidcConfigurationController : Controller
    {
        private readonly IConfiguration _configuration;
        private readonly ILogger<OidcConfigurationController> _logger;

        public OidcConfigurationController(IConfiguration configuration, ILogger<OidcConfigurationController> logger)
        {
            _configuration = configuration;
            _logger = logger;
        }

        [HttpGet("_configuration/{clientId}")]
        public IActionResult GetClientRequestParameters([FromRoute] string clientId)
        {
            // Return basic OIDC configuration for the SPA client
            var parameters = new
            {
                authority = _configuration["IdentityServer:Authority"] ?? "",
                client_id = clientId,
                redirect_uri = _configuration["IdentityServer:RedirectUri"] ?? "",
                post_logout_redirect_uri = _configuration["IdentityServer:PostLogoutRedirectUri"] ?? "",
                response_type = "code",
                scope = "openid profile Northwind.WebUIAPI"
            };
            return Ok(parameters);
        }
    }
}
