using System;
using System.Collections.Generic;
using System.Security.Claims;
using Duende.IdentityServer.Models;
using Duende.IdentityServer.Test;
using IdentityModel;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Data.SqlClient;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using Northwind.Application.Common.Interfaces;
using Northwind.Common;
using Northwind.Infrastructure.Files;

namespace Northwind.Infrastructure
{
    public static class DependencyInjection
    {
        public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration, IWebHostEnvironment environment)
        {
            services.AddScoped<IUserManager, UserManagerService>();
            services.AddTransient<INotificationService, NotificationService>();
            services.AddTransient<IDateTime, MachineDateTime>();
            services.AddTransient<ICsvFileBuilder, CsvFileBuilder>();

            var configurationbuilder = new ConfigurationBuilder()
                .AddJsonFile("appsettings.json")
                .AddJsonFile($"appsettings.Local.json", optional: true)
                .AddKeyPerFile("/opt/secret-volume", optional: true, reloadOnChange: true)
                .AddEnvironmentVariables()
                .Build();

            var connectionString = configuration.GetConnectionString("NorthwindDatabase");

            if (string.IsNullOrEmpty(connectionString))
            {
                SqlConnectionStringBuilder sqlConnectionStringBuilder = new SqlConnectionStringBuilder()
                {
                    DataSource = configurationbuilder["host"],
                    InitialCatalog = "Northwind",
                    PersistSecurityInfo = true,
                    UserID = configurationbuilder["username"],
                    Password = configurationbuilder["password"],
                    MultipleActiveResultSets = true
                };
                connectionString = sqlConnectionStringBuilder.ConnectionString;
            }

            var loggerfactory = services.BuildServiceProvider().GetService<ILoggerFactory>();
            loggerfactory.CreateLogger<ApplicationDbContext>().LogInformation("CONNECTION STRING: " + connectionString);

            services.AddDbContext<ApplicationDbContext>(options =>
                options.UseSqlServer(connectionString));

            services.AddDefaultIdentity<ApplicationUser>()
                .AddEntityFrameworkStores<ApplicationDbContext>();

            services.AddIdentityServer()
                .AddAspNetIdentity<ApplicationUser>()
                .AddInMemoryApiScopes(new List<ApiScope>
                {
                    new ApiScope("Northwind.WebUIAPI", "Northwind API")
                })
                .AddInMemoryClients(GetClients(environment));

            services.AddAuthentication()
                .AddJwtBearer();

            return services;
        }

        private static IEnumerable<Client> GetClients(IWebHostEnvironment environment)
        {
            var clients = new List<Client>
            {
                new Client
                {
                    ClientId = "Northwind.WebUI",
                    AllowedGrantTypes = GrantTypes.Code,
                    RequirePkce = true,
                    RequireClientSecret = false,
                    AllowedScopes = { "openid", "profile", "Northwind.WebUIAPI" },
                    RedirectUris = { "https://localhost/authentication/login-callback" },
                    PostLogoutRedirectUris = { "https://localhost/authentication/logout-callback" },
                    AllowedCorsOrigins = { "https://localhost" }
                }
            };

            if (environment.IsEnvironment("Test"))
            {
                clients.Add(new Client
                {
                    ClientId = "Northwind.IntegrationTests",
                    AllowedGrantTypes = { GrantType.ResourceOwnerPassword },
                    ClientSecrets = { new Secret("secret".Sha256()) },
                    AllowedScopes = { "Northwind.WebUIAPI", "openid", "profile" }
                });
            }

            return clients;
        }
    }
}
