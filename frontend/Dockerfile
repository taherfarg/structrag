FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Public values only: the Supabase URL, its publishable key, and the API URL are baked into the bundle.
ARG VITE_SUPABASE_URL VITE_SUPABASE_PUBLISHABLE_KEY VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
