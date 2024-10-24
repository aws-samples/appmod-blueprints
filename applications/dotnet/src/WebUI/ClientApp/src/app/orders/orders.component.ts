import { Component } from '@angular/core';
import { OrdersClient, OrdersListVm } from '../northwind-traders-api';

@Component({
  templateUrl: './orders.component.html'
})
export class OrdersComponent {

  ordersListVm: OrdersListVm = new OrdersListVm();

  constructor(client: OrdersClient) {
    client.getAll().subscribe(result => {
      this.ordersListVm = result;
    }, error => console.error(error));
  }
}
