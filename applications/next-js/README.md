# Ecommerce Lambda Function

This is a serverless application built with Rust and AWS Lambda that provides a backend for an e-commerce platform. 
It interacts with an AWS DynamoDB table to handle various operations related to products, categories, collections, 
and carts.

## Architecture 

This architecture defines the current state of the application.

![sls-shopping-cart.svg](./backend/api/assets/imgs/sls-shopping-cart.svg)

## Services

### Product Service

- `GET /products`: Retrieves a list of all products.
- `GET /product/<product_id>`: Retrieves details of a specific product.
- `GET /category/<category_id>/products`: Retrieves a list of products belonging to a specific category.
- `GET /collection/<collection_handle>`: Retrieves a list of products belonging to a specific collection.

### Category Service

- `GET /categories`: Retrieves a list of all categories.
- `GET /category/<category_id>`: Retrieves details of a specific category.

### Cart Service

- `POST /cart`: Creates a new cart.
- `POST /cart/<cart_id>/add`: Adds a product to the cart.
- `GET /cart/<cart_id>`: Retrieves the contents of a cart.
- `DELETE /cart/<cart_id>/remove/<product_id>`: Removes a product from the cart.

### UI Service

- `GET /menu`: Retrieves the menu structure (categories and collections).
- `GET /pages`: Retrieves a list of all pages.
- `GET /page/<page_id>`: Retrieves details of a specific page.

### To Do for Workshop
Wishlist service: Write a wishlist service that maintains wishlists for each individual user with name, Products, and
all other things normal to a wishlist.

We expect it to have the following routes:
- `POST /wishlist/new`: Creates a new wishlist
- `POST /wishlist/<wishlist_id>/add`: Adds a product to the wishlist
- `GET /wishlist/<wishlist_id>`: Retrieves the contents of the wishlist
- `POST /wishlist/<wishlist_id>/remove/<product_id>`: Removes a product from the wishlist

Sample prompt you can use to generate a skeleton for the wishlist service:
```
Implement the following routes:

- POST /wishlist/new: Creates a new wishlist, returns wishlist ID.
- POST /wishlist/<wishlist_id>/add: Adds a product to the specified wishlist.
- GET /wishlist/<wishlist_id>: Retrieves the contents of the specified wishlist.
- POST /wishlist/<wishlist_id>/remove/<product_id>: Removes a product from the wishlist.

Use AWS dynamodb to persist wishlist data (database or in-memory). Design for concurrent requests, scalability, and performance.

Requirements:

- Proper error handling and HTTP status codes.
- Unit tests for correctness.
- Code documentation and Rust best practices.
- Authentication and authorization for accessing/modifying wishlists.
- Consider caching mechanisms for performance.

Generate the Rust code for the wishlist service, including data structures, routes, handlers. 
Explain your implementation and design decisions briefly.
```

## Deployment Guide

To deploy this application to AWS Lambda, follow these steps:

1. **Set up AWS Credentials**: Configure your AWS credentials using the AWS CLI or by setting the `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` environment variables.
2. **Navigate to the backend folder**: Located in `./backend/api`.
3. **Use SAM CLI to deploy the backend**: Install the [SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) use the command `sam build --beta-features && sam deploy`
4. **Provide the API output to the frontend**: The SAM CLI will provide an output called `ShoppingCartApi` with a link, pass that link to the amplify environment variable `API_BASE_URL` allowing your frontend to access the API.
