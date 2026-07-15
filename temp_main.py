    request_kwargs = {
        'read_timeout': 60.0,
        'write_timeout': 30.0,
        'connect_timeout': 30.0,
        'pool_timeout': 10.0,
    }
    request = HTTPXRequest(**request_kwargs)
    application = Application.builder().token(TOKEN).request(request).build()
