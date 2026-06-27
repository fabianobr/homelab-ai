# FILE: test_main.py
import pytest
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.fixture(autouse=True)
def reset_stores():
    import routes
    for name, attr in vars(routes).items():
        if not name.startswith('_') and isinstance(attr, dict): attr.clear()
    for name, attr in vars(routes).items():
        if not name.startswith('_') and isinstance(attr, int): setattr(routes, name, 1)

@pytest.mark.asyncio
async def test_comissao():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        # Create a seller and post an item
        await client.post('/sellers', json={'name': 'Test Seller'})
        response = await client.post('/items', json={
            'title': 'Test Item',
            'description': 'This is a test item.',
            'category': 'Electronics',
            'photos': ['photo1.jpg'],
            'price': 100.00,
            'stock': 5,
            'sku': 'SKU123'
        })
        assert response.status_code == 201

        # Simulate a sale
        await client.post('/sales', json={'item_id': response.json()['id'], 'buyer_id': 'Buyer123'})

        # Check the seller's net amount after commission
        response = await client.get(f"/sellers/{response.json()['seller_id']}/balance")
        assert response.status_code == 200
        assert response.json()['seller_net'] == "90.00"

@pytest.mark.asyncio
async def test_programa_de_fidelidade():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        # Create a buyer and subscribe to Prime-like program
        await client.post('/buyers', json={'name': 'Test Buyer'})
        response = await client.post('/subscriptions', json={'buyer_id': 'Buyer123', 'program': 'Prime-like'})

        # Simulate a purchase over $21
        await client.post('/orders', json={
            'buyer_id': 'Buyer123',
            'items': [{'item_id': 1, 'quantity': 1}],
            'total_amount': 25.00,
            'shipping_address': '123 Test St'
        })

        # Check if shipping is free and cashback is credited
        response = await client.get('/buyers/Buyer123/wallet')
        assert response.status_code == 200
        assert response.json()['balance'] == "0.25"  # 1% of $25

@pytest.mark.asyncio
async def test_devolucao_sem_criterio():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        # Create a seller, buyer, post an item and simulate a sale
        await client.post('/sellers', json={'name': 'Test Seller'})
        response = await client.post('/items', json={
            'title': 'Test Item',
            'description': 'This is a test item.',
            'category': 'Electronics',
            'photos': ['photo1.jpg'],
            'price': 100.00,
            'stock': 5,
            'sku': 'SKU123'
        })
        await client.post('/sales', json={'item_id': response.json()['id'], 'buyer_id': 'Buyer123'})

        # Simulate a return request within 7 days
        response = await client.post('/returns', json={'order_id': 1, 'reason': 'Change of mind'})
        assert response.status_code == 201

        # Check if the refund process is initiated
        response = await client.get('/buyers/Buyer123/wallet')
        assert response.status_code == 200
        assert response.json()['balance'] == "90.00"  # Refund of $100 minus 10% commission

@pytest.mark.asyncio
async def test_recomendacao_e_aprendizado():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        # Create a buyer and simulate navigation sessions
        await client.post('/buyers', json={'name': 'Test Buyer'})
        await client.post('/navigation_sessions', json={'buyer_id': 'Buyer123', 'categories': ['Electronics'], 'queries': ['laptop']})

        # Access the recommendations section
        response = await client.get('/buyers/Buyer123/recommendations')
        assert response.status_code == 200
        assert len(response.json()['products']) > 0
        assert len(response.json()['contents']) > 0


@pytest.mark.asyncio
async def test_anuncio_pode_ser_editado_e_desativado():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/sellers', json={'name': 'Seller One'})
        response = await client.post('/items', json={
            'title': 'Notebook',
            'description': 'Gaming notebook',
            'category': 'Electronics > Computers',
            'photos': ['p1.jpg'],
            'price': 1500.00,
            'stock': 2,
            'sku': 'NB-1'
        })
        assert response.status_code == 201
        item_id = response.json()['id']

        response = await client.put(f'/items/{item_id}', json={
            'price': 1300.00,
            'stock': 4,
            'description': 'Updated description'
        })
        assert response.status_code == 200
        assert response.json()['price'] == 1300.0 or response.json()['price'] == 1300
        assert response.json()['stock'] == 4

        response = await client.post(f'/items/{item_id}/deactivate')
        assert response.status_code == 200
        assert response.json()['active'] is False


@pytest.mark.asyncio
async def test_anuncio_rejeita_foto_e_categoria_invalidas():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/items', json={
            'title': 'Bad Item',
            'description': 'Invalid',
            'category': 'A > B > C > D',
            'photos': [],
            'price': 10.00,
            'stock': 1,
            'sku': 'BAD-1'
        })
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_checkout_por_wallet_deduz_saldo():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/buyers', json={'name': 'Wallet Buyer'})
        await client.post('/wallets/Buyer123/credit', json={'amount': 50.00})
        await client.post('/sellers', json={'name': 'Seller Wallet'})
        response = await client.post('/items', json={
            'title': 'Phone',
            'description': 'Useful',
            'category': 'Electronics > Phones',
            'photos': ['p1.jpg'],
            'price': 30.00,
            'stock': 1,
            'sku': 'PH-1'
        })
        item_id = response.json()['id']

        response = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'wallet',
            'items': [{'item_id': item_id, 'quantity': 1}],
            'shipping_address': 'Street 1'
        })
        assert response.status_code == 200
        assert response.json()['status'] == 'approved'

        wallet = await client.get('/buyers/Buyer123/wallet')
        assert wallet.json()['balance'] == '20.00'


@pytest.mark.asyncio
async def test_checkout_por_cartao_parceiro_aprova_e_gateway_invalido_rejeita():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/buyers', json={'name': 'Card Buyer'})
        await client.post('/sellers', json={'name': 'Seller Card'})
        response = await client.post('/items', json={
            'title': 'Tablet',
            'description': 'Portable',
            'category': 'Electronics > Tablets',
            'photos': ['p1.jpg'],
            'price': 80.00,
            'stock': 1,
            'sku': 'TB-1'
        })
        item_id = response.json()['id']

        response = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'partner_card',
            'gateway': 'partner_a',
            'items': [{'item_id': item_id, 'quantity': 1}],
            'shipping_address': 'Street 2'
        })
        assert response.status_code == 200
        assert response.json()['gateway'] == 'partner_a'

        response = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'partner_card',
            'gateway': 'invalid_gateway',
            'items': [{'item_id': item_id, 'quantity': 1}],
            'shipping_address': 'Street 2'
        })
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_logistica_quote_e_despacho():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/buyers', json={'name': 'Log Buyer'})
        await client.post('/sellers', json={'name': 'Log Seller'})
        response = await client.post('/items', json={
            'title': 'Camera',
            'description': 'Digital camera',
            'category': 'Electronics > Cameras',
            'photos': ['p1.jpg'],
            'price': 120.00,
            'stock': 1,
            'sku': 'CAM-1'
        })
        item_id = response.json()['id']
        response = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'partner_card',
            'gateway': 'partner_a',
            'items': [{'item_id': item_id, 'quantity': 1}],
            'shipping_address': 'Street 3'
        })
        order_id = response.json()['order_id']

        quote = await client.post('/shipping/quote', json={
            'items': [{'item_id': item_id, 'quantity': 1}]
        })
        assert quote.status_code == 200
        assert len(quote.json()['quotes']) == 2

        dispatch = await client.post('/shipping/dispatch', json={
            'order_id': order_id,
            'carrier': 'carrier_a'
        })
        assert dispatch.status_code == 200
        assert dispatch.json()['tracking_code'].startswith('TRK-')

        shipment = await client.get(f"/shipments/{dispatch.json()['id']}")
        assert shipment.status_code == 200
        assert shipment.json()['carrier'] == 'carrier_a'


@pytest.mark.asyncio
async def test_seller_central_e_reputacao_publica():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/sellers', json={'name': 'Central Seller'})
        response = await client.post('/items', json={
            'title': 'Monitor',
            'description': '4K monitor',
            'category': 'Electronics > Displays',
            'photos': ['p1.jpg'],
            'price': 200.00,
            'stock': 1,
            'sku': 'MON-1'
        })
        item_id = response.json()['id']
        await client.post('/buyers', json={'name': 'Central Buyer'})
        await client.post('/sales', json={'item_id': item_id, 'buyer_id': 'Buyer123'})
        await client.post('/sellers/Seller123/reviews', json={'stars': 5, 'returned': False, 'complaint': False})

        dashboard = await client.get('/sellers/Seller123/central')
        assert dashboard.status_code == 200
        assert dashboard.json()['sales_count'] == 1
        assert dashboard.json()['active_items'] == 1
        assert dashboard.json()['commission_retained'] == '20.00'

        reputation = await client.get('/sellers/Seller123/reputation')
        assert reputation.status_code == 200
        assert reputation.json()['average_rating'] == '5.00'
        assert reputation.json()['reputation_score'] != '0.00'


@pytest.mark.asyncio
async def test_fluxo_devolucao_e_processamento():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/buyers', json={'name': 'Return Buyer'})
        await client.post('/sellers', json={'name': 'Return Seller'})
        response = await client.post('/items', json={
            'title': 'Headphones',
            'description': 'Wireless',
            'category': 'Electronics > Audio',
            'photos': ['p1.jpg'],
            'price': 100.00,
            'stock': 1,
            'sku': 'HD-1'
        })
        item_id = response.json()['id']
        await client.post('/sales', json={'item_id': item_id, 'buyer_id': 'Buyer123'})

        response = await client.post('/returns', json={'order_id': 1, 'reason': 'Change of mind'})
        assert response.status_code == 201
        return_id = response.json()['id']

        stored = await client.get(f'/returns/{return_id}')
        assert stored.status_code == 200
        assert stored.json()['status'] == 'requested'

        processed = await client.post(f'/returns/{return_id}/process')
        assert processed.status_code == 200
        assert processed.json()['status'] == 'processed'


@pytest.mark.asyncio
async def test_launch_readiness_flips_when_controls_are_enabled():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        readiness = await client.get('/launch/readiness')
        assert readiness.status_code == 200
        assert readiness.json()['ready'] is False
        assert readiness.json()['environments']['production']['deployed'] is False

        response = await client.post('/launch/environments/production/deploy', json={
            'deployed': True,
            'healthy': True,
        })
        assert response.status_code == 200

        response = await client.post('/launch/finance', json={
            'invoice_enabled': True,
            'payouts_enabled': True,
            'repasse_cycle_days': 3,
        })
        assert response.status_code == 200
        assert response.json()['payouts_enabled'] is True

        response = await client.post('/launch/security/mfa', json={
            'mfa_required': True,
            'mfa_for_sellers': True,
            'mfa_for_finance': True,
        })
        assert response.status_code == 200

        readiness = await client.get('/launch/readiness')
        assert readiness.status_code == 200
        assert readiness.json()['ready'] is True
        assert readiness.json()['finance']['repasse_cycle_days'] == 3


@pytest.mark.asyncio
async def test_persistencia_salva_e_restaura_estado(tmp_path):
    import routes

    routes.DB_PATH = str(tmp_path / "marketplace_state.sqlite3")
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/sellers', json={'name': 'Persistent Seller'})
        response = await client.post('/items', json={
            'title': 'Persistent Item',
            'description': 'Stored across restart',
            'category': 'Electronics',
            'photos': ['p1.jpg'],
            'price': 100.00,
            'stock': 1,
            'sku': 'PERSIST-1'
        })
        await client.post('/sales', json={'item_id': response.json()['id'], 'buyer_id': 'Buyer123'})

        saved = await client.post('/persistence/save')
        assert saved.status_code == 200
        assert saved.json()['saved'] is True

        for name, attr in vars(routes).items():
            if not name.startswith('_') and isinstance(attr, dict):
                attr.clear()
        for name, attr in vars(routes).items():
            if not name.startswith('_') and isinstance(attr, int):
                setattr(routes, name, 1)

        loaded = await client.post('/persistence/load')
        assert loaded.status_code == 200
        assert loaded.json()['loaded'] is True

        balance = await client.get('/sellers/Seller123/balance')
        assert balance.status_code == 200
        assert balance.json()['seller_net'] == '90.00'


@pytest.mark.asyncio
async def test_auth_buyer_login_sem_mfa_e_admin_exige_mfa():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        buyer = await client.post('/auth/register', json={
            'email': 'buyer@example.com',
            'password': 'secret',
            'role': 'buyer',
        })
        assert buyer.status_code == 201
        assert buyer.json()['mfa_enabled'] is False

        login = await client.post('/auth/login', json={
            'email': 'buyer@example.com',
            'password': 'secret',
        })
        assert login.status_code == 200
        buyer_token = login.json()['access_token']

        me = await client.get('/auth/me', headers={'Authorization': f'Bearer {buyer_token}'})
        assert me.status_code == 200
        assert me.json()['role'] == 'buyer'

        denied = await client.get('/admin/summary', headers={'Authorization': f'Bearer {buyer_token}'})
        assert denied.status_code == 403

        admin = await client.post('/auth/register', json={
            'email': 'admin@example.com',
            'password': 'secret',
            'role': 'admin',
        })
        assert admin.status_code == 201
        assert admin.json()['mfa_enabled'] is True

        login = await client.post('/auth/login', json={
            'email': 'admin@example.com',
            'password': 'secret',
        })
        assert login.status_code == 200
        assert login.json()['mfa_required'] is True

        verify = await client.post('/auth/mfa/verify', json={
            'challenge_id': login.json()['challenge_id'],
            'code': '123456',
        })
        assert verify.status_code == 200
        admin_token = verify.json()['access_token']

        summary = await client.get('/admin/summary', headers={'Authorization': f'Bearer {admin_token}'})
        assert summary.status_code == 200
        assert summary.json()['users'] == 2


@pytest.mark.asyncio
async def test_integracoes_configuraveis_antifraude_e_metricas_checkout():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        status = await client.get('/integrations/status')
        assert status.status_code == 200
        assert 'partner_a' in status.json()['payments']

        await client.post('/integrations/payments/partner_a', json={'enabled': True, 'healthy': True, 'mode': 'sandbox'})
        await client.post('/buyers', json={'name': 'Risk Buyer'})
        await client.post('/sellers', json={'name': 'Risk Seller'})
        item = await client.post('/items', json={
            'title': 'Risk Item',
            'description': 'Fraud check',
            'category': 'Electronics',
            'photos': ['p1.jpg'],
            'price': 40.00,
            'stock': 1,
            'sku': 'RISK-1'
        })

        blocked = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'partner_card',
            'gateway': 'partner_a',
            'items': [{'item_id': item.json()['id'], 'quantity': 1}],
            'shipping_address': 'Street',
            'risk_score': 90,
        })
        assert blocked.status_code == 402

        approved = await client.post('/checkout', json={
            'buyer_id': 'Buyer123',
            'payment_method': 'partner_card',
            'gateway': 'partner_a',
            'items': [{'item_id': item.json()['id'], 'quantity': 1}],
            'shipping_address': 'Street',
            'risk_score': 10,
        })
        assert approved.status_code == 200

        metrics = await client.get('/ops/checkout/metrics')
        assert metrics.status_code == 200
        assert metrics.json()['total'] == 2
        assert metrics.json()['blocked'] == 1


@pytest.mark.asyncio
async def test_smoke_rollback_e_notificacao_de_launch():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        checkpoint = await client.post('/ops/rollback/checkpoint')
        assert checkpoint.status_code == 200

        await client.post('/launch/environments/production/deploy', json={'deployed': True, 'healthy': True})
        await client.post('/launch/finance', json={'invoice_enabled': True, 'payouts_enabled': True, 'repasse_cycle_days': 3})
        await client.post('/launch/security/mfa', json={'mfa_required': True, 'mfa_for_sellers': True, 'mfa_for_finance': True})
        notification = await client.post('/integrations/notifications/email/test', json={'target': 'ops@example.com'})
        assert notification.status_code == 200
        assert notification.json()['status'] == 'sent'

        smoke = await client.post('/ops/smoke')
        assert smoke.status_code == 200
        assert smoke.json()['passed'] is True

        await client.post('/launch/environments/production/deploy', json={'deployed': False, 'healthy': False})
        restored = await client.post(f"/ops/rollback/{checkpoint.json()['checkpoint_id']}/restore")
        assert restored.status_code == 200

        readiness = await client.get('/launch/readiness')
        assert readiness.status_code == 200
        assert readiness.json()['environments']['production']['deployed'] is False


@pytest.mark.asyncio
async def test_demo_investidor_monta_fluxo_completo_sandbox():
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/demo/investor-seed')
        assert response.status_code == 200
        data = response.json()
        assert data['mode'] == 'sandbox'
        assert data['checkout']['status'] == 'approved'
        assert data['shipment']['tracking_code'].startswith('TRK-')
        assert data['readiness']['ready'] is True
        assert data['smoke']['passed'] is True
        assert data['seller_central']['sales_count'] >= 1
        assert 'sandbox' in data['disclaimer']
