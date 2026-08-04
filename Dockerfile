FROM php:8.2-apache-bookworm

# Install dependencies
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    libfreetype6-dev \
    libpq-dev \
    postgresql-client \
    libsnmp-dev \
    iputils-ping \
    fping \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install gd pdo pdo_pgsql pgsql snmp calendar

# Enable Apache mod_rewrite and set ServerName
RUN a2enmod rewrite \
    && echo "ServerName localhost" >> /etc/apache2/apache2.conf

# Copiar os arquivos da aplicação (pasta public_html vira o /var/www/html)
COPY public_html/ /var/www/html/

# Copiar os arquivos JSON de dados
COPY status_maquinas.json status_usuarios.json status_usuarios_anterior.json status_usuarios_historico.json /var/www/

# Ajustar permissões para que o Apache consiga acessar e gravar os arquivos
RUN chown -R www-data:www-data /var/www/html /var/www/*.json && \
    chmod 664 /var/www/*.json

# Expor a porta 80 (padrão do Apache) para o Render
EXPOSE 80
