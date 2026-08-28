FROM node:22-alpine

WORKDIR /app

ARG CONTROL_PLANE_API_URL=http://127.0.0.1:8080
ENV CONTROL_PLANE_API_URL=${CONTROL_PLANE_API_URL}

COPY package.json ./
RUN npm install --ignore-scripts

COPY . .
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "start"]
