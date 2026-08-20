import os
import uvicorn

if __name__ == '__main__':
    # Bind 0.0.0.0 so Lightning's public/private proxy can expose the worker.
    uvicorn.run('lightning_worker.main:app', host='0.0.0.0', port=int(os.getenv('PORT','8000')), reload=False)
