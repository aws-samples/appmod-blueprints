import { Component } from '@angular/core';
import { CustomersClient, CustomersListVm } from '../northwind-traders-api';

@Component({
  standalone: false,
  selector: 'app-customers',
  templateUrl: './customers.component.html'
})
export class CustomersComponent {

  public vm: CustomersListVm = new CustomersListVm();

  constructor(private client: CustomersClient) {
    client.getAll().subscribe(result => {
      this.vm = result;
    }, error => console.error(error));
  }
}
