# GMO Modules — what is developed and how it is wired

The Business Intake agent (`posgmo-factory/agents/business_intake/`) reads this file
to know what GMO already has **before** it calls any AI model. Keep it current:
when a module or agent ships, add it here. No code change is needed.

An entry here is a **candidate capability, not proof of implementation**. The agent
checks every route, stored procedure and table listed under "wiring" against the
repository knowledge files, and only treats what it can verify as implementation evidence.
Be precise about a module's real domain: a generic-sounding name that is domain-specific
(e.g. a credit-oriented follow-up log) must say so in `does`.

## Format

Each `###` entry is one module or agent. The agent reads these lines:

- `id`: unique, camelCase
- `kind`: `module` or `agent`
- `keywords`: comma-separated English and Spanish words a business owner might say; the request is matched against them
- `does`: one or two plain sentences
- `frontend` / `backend` / `database` / `agents`: how it is wired. Write `not documented yet` when unknown, never a guess.
- `domain` / `owner` (optional): the bounded context that owns it (e.g. `POS GMO retail`, `SmartLoans credit`).
- `mobile` / `web` (optional): `available`, `partial` or `missing` in the existing GMO mobile app / web platform,
  plus a short note. Leave it out when unknown — the agent then reports UNKNOWN.
- `configuration` (optional): what a company can set up **without development**, and where it is stored.
- `dependencies` (optional): other capabilities it needs.

Wiring comes from `Backend/backend_routes.json.json`, `Backend/backend_stored_procedures.json.json`,
`Database/structure_database.csv`, `posgmo-factory/ecosystem_graph/` (verified frontend → backend chains)
and `LoanAgents_SmartLoans/main.py` (agent endpoints). Last reviewed: 2026-10-06.

---

## POS GMO

### Company onboarding and module activation
- id: companyOnboarding
- kind: module
- keywords: registrar empresa, registrar mi empresa, registrar mi negocio, abrir mi negocio, abrir un negocio, nuevo negocio, nueva empresa, crear una empresa, crear una nueva empresa, empezar mi negocio, register company, register my company, open my business, new business, start my business, onboarding, alta de empresa
- domain: GMO platform (tenancy)
- owner: GMO platform
- does: Joins a new business to GMO as a company (tenant): company record, branches, which modules are active for the company, users of the company and their roles/permissions.
- frontend: not documented yet (no self-service onboarding screen verified)
- backend: /companies → routes_/companies.py; /companiesBranches → routes_/companiesBranches.py; /users → routes_/users.py; /login → routes_/login.py. No route or stored procedure is documented for activating modules or assigning roles/permissions.
- database: companies, companiesBranch, company_modules, modules, permissions, roles, role_permissions, userCompanies
- configuration: activate or deactivate modules per company (company_modules: companyId, moduleId, active); branches (companiesBranch); user ↔ company with role and default branch (userCompanies); roles and permissions per module (roles, permissions, role_permissions)
- dependencies: users

### Companies (multi-company)
- id: companies
- kind: module
- keywords: company, companies, empresa, empresas, negocio, business, branch, branches, sucursal, sucursales, tenant
- does: Each business is a company on POS GMO (Company 1 → Company N) with its own data, branches and enabled modules. companyId always comes from the logged-in session.
- frontend: not documented yet
- backend: /companies → routes_/companies.py; /companiesBranches → routes_/companiesBranches.py
- database: companies, companiesBranch, company_modules, userCompanies

### Clients (CRUD)
- id: clients
- kind: module
- keywords: client, clients, customer, customers, cliente, clientes, registrar clientes, register clients, crm, contacto, contactos
- does: Register, edit, list and delete each company's clients. Client types: pos (store shopper), borrower, lender, both, lawyer.
- frontend: clientsApi.ts (verified in ecosystem_graph)
- backend: /clients → routes_/clients.py
- database: clients

### Client follow-up
- id: clientFollowUp
- kind: module
- keywords: follow up, follow-up, followup, seguimiento, dar seguimiento, seguir, track client, recordatorio, pendiente, status del cliente, proceso del cliente
- domain: SmartLoans credit / collections
- does: Monitoring and collections follow-up log per client (status, reason, note, due date, assigned person). Its riskStatus (on_track / at_risk / default) feeds the internal credit score, so it is credit/SmartLoans-oriented, not a generic activity log.
- frontend: not documented yet
- backend: POST /all_clientFollowUps (used by LoanAgents_SmartLoans tools/backend_api.py)
- database: clientFollowUps (live database; not in the schema snapshot); design in posgmo-factory/tests/prd_clientFollowUp.json

### Clients map
- id: clientMaps
- kind: module
- keywords: map, maps, mapa, mapas, location, ubicación, ubicacion, dirección, direccion, address, ruta, rutas, route
- does: See clients' locations on a map.
- frontend: not documented yet
- backend: /api/geocode (address geocoding); map page wiring not documented yet
- database: addresses

### QR codes
- id: qr
- kind: module
- keywords: qr, código qr, codigo qr, qr code, identificación, identificacion
- does: A QR code per client for fast identification, generated during client registration.
- frontend: client registration wizard (QR step)
- backend: not documented yet
- database: client QR image URL (qrBlobUrl) on the client record

### KYC (identity verification)
- id: kyc
- kind: module
- keywords: kyc, identidad, identity, ine, pasaporte, passport, licencia, verificar, verification, verificación, verificacion, selfie, rostro, face, liveness, documento, id document
- does: Identity verification: ID document capture with OCR, selfie/face match and liveness check.
- frontend: client registration wizard (Documento, Captura, Verificación steps)
- backend: /clientFaceRecognitions → routes_/clientFaceRecognitions.py; /ocr → routes_/ocr.py
- database: ClientFaceRecognitions

### Suppliers
- id: suppliers
- kind: module
- keywords: supplier, suppliers, proveedor, proveedores, vendor, vendors
- does: Supplier records per company.
- frontend: not documented yet
- backend: /suppliers → routes_/suppliers.py
- database: not in the schema snapshot; design in posgmo-factory/tests/prd_supplier.json

### Products and services
- id: products
- kind: module
- keywords: product, products, producto, productos, service, services, servicio, servicios, catalog, catálogo, catalogo, price, prices, precio, precios, category, categoría
- does: Product and service catalog with categories, options and packaging.
- configuration: the company's own product categories (productCategories.companyId), subcategories and product options
- frontend: not documented yet
- backend: /products → routes_/products.py; /productCategories → routes_/productCategories.py
- database: products, productCategories, subCategories, productDetails, productOptions, productOptionChoices

### Sales (point of sale)
- id: sales
- kind: module
- keywords: sale, sales, sell, venta, ventas, vender, cobrar, charge, income, ingreso, ingresos, caja, cash register, pos, punto de venta, payment, pago, pagos
- does: Point-of-sale sales / income and cash register sessions.
- frontend: incomeApi.ts (verified in ecosystem_graph)
- backend: /income → routes_/income.py (sp_income); /cashRegister → routes_/cashRegister.py
- database: income, incomeDetails, cashRegisterSessions, cashRegisterMovements

### Expenses
- id: expenses
- kind: module
- keywords: expense, expenses, gasto, gastos, cost, costs, costo, costos, bill, bills, factura de compra, receipt, recibo
- does: Record expenses, including AI receipt reading and categorization.
- frontend: expensesApi.ts (verified in ecosystem_graph)
- backend: /expenses → routes_/expenses.py
- database: expenses, expenseDetails, expenseDetailOptions

### Inventory
- id: inventory
- kind: module
- keywords: inventory, inventario, stock, existencias, almacén, almacen, warehouse
- does: Stock levels and inventory movements per product.
- frontend: not documented yet
- backend: not documented yet (no /inventory route in the Backend knowledge files)
- database: inventoryStock, inventoryMovements

### Manufacturing / costing
- id: manufacturing
- kind: module
- keywords: manufacturing, manufactura, production, producción, produccion, cost of service, costo del servicio, costo de cada servicio, receta, recipe, insumos, materials, materia prima
- does: Determines the real cost of every product or service from its inputs.
- frontend: not documented yet
- backend: /manufacturing → routes_/manufacturing.py; /costRules → routes_/costRules.py
- database: manufactures, costRules

### Orders
- id: orders
- kind: module
- keywords: order, orders, pedido, pedidos, orden, órdenes, ordenes, delivery, entrega, envío, envio, shipment, tracking
- does: Customer orders with status and tracking.
- frontend: not documented yet
- backend: /orders → routes_/orders.py (sp_orders, sp_orders_list, sp_orders_tracking_status, sp_orders_products_one); /shipments → routes_/shipments.py
- database: orders, orderDetails, orderStatuses, orderTracking, shipments

### Tickets and receipts (SMS, WhatsApp, email)
- id: tickets
- kind: module
- keywords: ticket, tickets, receipt, recibo, comprobante, nota, sms, whatsapp, email, correo
- does: Tickets and receipts delivered to the client by SMS, WhatsApp and email.
- frontend: not documented yet
- backend: /tickets → routes_/tickets.py; /messageTickets → routes_/messageTickets.py; /whatsapp → routes_/whatsapp.py
- database: tickets, messageTickets, whatsapp_messages

### Rewards
- id: rewards
- kind: module
- keywords: reward, rewards, recompensa, recompensas, points, puntos, loyalty, lealtad, fidelidad, premio, premios, beneficio, beneficios
- does: Loyalty points earned from sales; balance, history and benefits.
- frontend: rewardsApi.ts (verified in ecosystem_graph)
- backend: earn points on income (modules.rewards.earn_points_for_income)
- database: reward points and reward transactions (live database; not in the schema snapshot)

### Promotions
- id: promotions
- kind: module
- keywords: promotion, promotions, promoción, promocion, promociones, discount, descuento, descuentos, campaign, campaña, oferta, ofertas
- does: Promotions and discount campaigns targeted at clients.
- configuration: the company's promotions and their targets (promotions, promotion_targets)
- frontend: not documented yet
- backend: not documented yet
- database: promotions, promotion_targets

### Accounting
- id: accounting
- kind: module
- keywords: accounting, contabilidad, balance, income statement, estado de resultados, ledger, finanzas, finance, impuestos, taxes
- does: Accounting ledger, balance and income statement built from sales and expenses.
- frontend: not documented yet
- backend: not documented yet
- database: not documented yet

### Dashboard
- id: dashboard
- kind: module
- keywords: dashboard, tablero, kpi, kpis, reporte, reportes, report, reports, métricas, metricas, gráficas, graficas, charts
- does: Business KPIs, charts and reports.
- frontend: not documented yet
- backend: not documented yet
- database: not documented yet

### Employees
- id: employees
- kind: module
- keywords: employee, employees, empleado, empleados, staff, personal, departamento, department, contractor, contratista, nómina, nomina
- does: Employee records, departments, employment types and contractors.
- frontend: not documented yet
- backend: /employees → routes_/employees.py (sp_employees); /departaments, /employmentTypes, /contractors
- database: employees, departments, employmentTypes, contractors

### Users, roles and permissions
- id: users
- kind: module
- keywords: user, users, usuario, usuarios, role, roles, rol, permission, permissions, permiso, permisos, login, acceso, access, cuenta, account
- does: Users of each company with roles and permissions; login.
- configuration: roles and their permissions per module (roles, permissions, role_permissions); each user's company, role and default branch (userCompanies)
- frontend: not documented yet
- backend: /users → routes_/users.py (sp_users); /login → routes_/login.py (sp_login)
- database: users, roles, permissions, role_permissions, userCompanies, logins

### Alerts
- id: alerts
- kind: module
- keywords: alert, alerts, alerta, alertas, aviso, avisos, warning
- does: Alerts to the business about events that need attention.
- frontend: not documented yet
- backend: not documented yet
- database: not documented yet

### Emails
- id: emails
- kind: module
- keywords: email, emails, correo, correos, mail
- does: Sending emails to clients and users.
- frontend: not documented yet
- backend: /contact_email → routes_/contact_email.py
- database: not documented yet

### Notifications (push, WhatsApp, SMS)
- id: notifications
- kind: module
- keywords: notification, notifications, notificación, notificacion, notificaciones, push, whatsapp, sms, mensaje, mensajes, message, messages, recordatorio, reminder
- does: Push, WhatsApp and SMS notifications to clients. Cross-cutting: used by POS, Rewards and SmartLoans.
- frontend: not documented yet
- backend: /pushNotifications → routes_/pushNotifications.py (sp_pushNotifications, sp_pushNotifications_all, sp_pushNotifications_recordDelivery); /whatsapp → routes_/whatsapp.py
- database: NotificationDeliveries, whatsapp_messages

### Marketplace (eBay · MercadoLibre)
- id: marketplace
- kind: module
- keywords: marketplace, mercadolibre, mercado libre, ebay, amazon, publicar, listing, listings, vender en línea, online store, tienda en línea
- does: Unified product catalog and listings published to marketplaces, with marketplace orders.
- domain: Omnichannel marketplace aggregation
- frontend: not documented yet
- backend: /unifiedProducts, /productMatches, /sellListings (sp_sellListings), /marketplaceOrders, /mercadolibre, /ebay_proxy
- database: unifiedProducts, productMatches, sellListings, marketplaceOrders

## POS GMO — AI agents

### Support agents
- id: supportAgents
- kind: agent
- keywords: support, soporte, ayuda, help, problema, problem, duda, dudas, question
- does: AI support agents inside POS that solve users' questions and problems immediately (clients, sales, expenses, accounting, rewards).
- agents: LoanAgents_SmartLoans /support/pos-clients, /support/pos-income, /support/pos-expenses, /support/pos-accounting, /support/pos-rewards

### Client follow-up suggestion agent
- id: clientFollowUpAgent
- kind: agent
- keywords: follow up, seguimiento, riesgo, risk, cobranza, collections, next action, siguiente acción
- does: Suggests each client's next follow-up action and risk status (advisory only).
- agents: LoanAgents_SmartLoans /clients/follow-up-suggestion

### Expense receipt agent
- id: expenseReceiptAgent
- kind: agent
- keywords: receipt, recibo, ticket de compra, foto del ticket, categorize, categorizar, factura
- does: Reads a photo of a purchase receipt and proposes the expense, supplier and products; categorizes expenses.
- agents: LoanAgents_SmartLoans /expenses/extract-ticket, /expenses/categorize

### Inventory registration agent
- id: inventoryRegistrationAgent
- kind: agent
- keywords: register inventory, registrar inventario, capturar inventario, alta de productos, cargar inventario
- does: Helps register all of a company's inventory.
- agents: not documented yet

### Restock agent
- id: restockAgent
- kind: agent
- keywords: restock, reabastecer, comprar más, buy more, faltante, se acaba, low stock, poco inventario, reorden
- does: Notifies when more inventory needs to be bought.
- agents: not documented yet

### Service payment agent
- id: servicePaymentAgent
- kind: agent
- keywords: pay services, pagar servicios, pago de servicios, bills, recibos, luz, agua, internet, teléfono, telefono
- does: Pays the company's services and bills.
- agents: not documented yet

### Cash register review agent
- id: cashRegisterAgent
- kind: agent
- keywords: corte de caja, cierre de caja, cash closeout, cuadrar caja, faltante de caja
- does: Reviews cash register close-outs and flags differences.
- agents: LoanAgents_SmartLoans /cash-register/review-closeout

### Order triage agent
- id: orderTriageAgent
- kind: agent
- keywords: pedidos atrasados, stale orders, order triage, pedidos pendientes
- does: Summarizes stale or stuck orders that need attention.
- agents: LoanAgents_SmartLoans /orders/triage-summary

### WhatsApp reservations agent
- id: whatsappReservationsAgent
- kind: agent
- keywords: reservation, reservations, reservación, reservacion, reservaciones, cita, citas, appointment, appointments, agenda
- does: Handles reservations and appointments through WhatsApp conversations.
- agents: LoanAgents_SmartLoans /support/whatsapp-reservations

## SmartLoans

### Loans between people
- id: loans
- kind: module
- keywords: loan, loans, préstamo, prestamo, préstamos, prestamos, prestar, lend, lender, prestamista, borrower, solicitante, crédito, credito, pagaré, pagare, contrato, contract
- does: People who need money borrow from people who want to lend it: requests, offers, proposals, negotiation chat, contracts and pagaré, wallets, automatic payments.
- frontend: not documented yet
- backend: /loans (sp_loans), /loanOffers (sp_loanOffers), /loanProposals (sp_loanProposals), /loanChat (sp_loanChat), /credit-score, /digitalContracts, /signatures, /disbursement, /wallet, /stripe, /automated-payments, /onboarding-reminders
- database: loans, loanOffers, loanProposals, loanConversations, loanMessages, loanInstallments, clientWallets, walletTransactions, savedPaymentMethods

### Legal recovery
- id: legalRecovery
- kind: module
- keywords: legal, abogado, abogada, abogados, lawyer, lawyers, despacho, bufete, law firm, juicio, demanda, lawsuit, caso legal, casos legales, legal case, proceso legal, legal process, embargo
- domain: SmartLoans credit / legal recovery
- owner: SmartLoans
- does: Legal cases for overdue loans (juicio mercantil). Each case is tied to a loan, its borrower and its lender, with an optional lawyer.
- frontend: not documented yet
- backend: /legalCases → routes_/legalCases.py (sp_legalCases)
- database: legalCases (loanId, borrowerClientId and lenderClientId are NOT NULL; lawyerClientId is optional)

## Arcade / Casino

### Arcade / Casino
- id: arcade
- kind: module
- keywords: arcade, casino, game, games, juego, juegos, fichas, credits, créditos de juego, apuesta
- does: Games with separate gaming credits, connected to Rewards.
- frontend: not documented yet
- backend: not documented yet
- database: not in the schema snapshot; designs in posgmo-factory/tests/prd_arcade*.json
