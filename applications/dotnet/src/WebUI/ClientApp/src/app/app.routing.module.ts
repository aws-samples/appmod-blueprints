import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { CustomersComponent } from './customers/customers.component';
import { HomeComponent } from './home/home.component';
import { ProductsComponent } from './products/products.component';
import { AuthorizeGuard } from '../api-authorization/authorize.guard';
import { OrdersComponent } from './orders/orders.component';

const routes: Routes = [
  { path: '', component: HomeComponent, pathMatch: 'full' },
  { path: 'northwind-app', component: HomeComponent},
  { path: 'customers', component: CustomersComponent, canActivate: [AuthorizeGuard] },
  { path: 'northwind-app/customers', component: CustomersComponent, canActivate: [AuthorizeGuard] },
  { path: 'products', component: ProductsComponent },
  { path: 'northwind-app/products', component: ProductsComponent },
  { path: 'orders', component: OrdersComponent },
  { path: 'northwind-app/orders', component: OrdersComponent }
];

@NgModule({
    imports: [RouterModule.forRoot(routes)],
    exports: [RouterModule]
})
export class AppRoutingModule { }
