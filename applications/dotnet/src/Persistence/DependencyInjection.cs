using Microsoft.Data.SqlClient;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Northwind.Application.Common.Interfaces;
using System;

namespace Northwind.Persistence
{
    public static class DependencyInjection
    {
        public static IServiceCollection AddPersistence(this IServiceCollection services, IConfiguration configuration)
        {
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
                    InitialCatalog = "NorthwindTraders",
                    PersistSecurityInfo = true,
                    UserID = configurationbuilder["username"],
                    Password = configurationbuilder["password"],
                    MultipleActiveResultSets = true
                };
                connectionString = sqlConnectionStringBuilder.ConnectionString;
            }
            var loggerfactory = services.BuildServiceProvider().GetService<ILoggerFactory>();
            loggerfactory.CreateLogger<NorthwindDbContext>().LogInformation("CONNECTION STRING: " + connectionString);
            

            services.AddDbContext<NorthwindDbContext>(options =>
                options.UseSqlServer(connectionString));

            services.AddScoped<INorthwindDbContext>(provider => provider.GetService<NorthwindDbContext>());

            return services;
        }
    }
}
