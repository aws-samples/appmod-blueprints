using Amazon.CDK;

namespace NorthwindCdk
{
    sealed class Program
    {
        public static void Main(string[] args)
        {
            var app = new App();
            new NorthwindCdkStack(app, "NorthwindCdkStack");

            app.Synth();
        }
    }
}
