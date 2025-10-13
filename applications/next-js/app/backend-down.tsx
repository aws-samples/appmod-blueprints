import React from 'react';

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-white">
      <div className="flex max-w-md flex-col items-center px-4 py-8">
        <div className="mb-8 flex items-center">
          <h1 className="mr-4 text-5xl font-bold text-gray-800">500</h1>
          <div className="h-12 border-l border-gray-300"></div>
          <p className="ml-4 text-xl text-gray-600">
            Looks like the backend is down, please deploy it and try again!
          </p>
        </div>
      </div>
    </div>
  );
}
