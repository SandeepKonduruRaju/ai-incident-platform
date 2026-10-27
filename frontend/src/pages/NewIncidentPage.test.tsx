import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ApiError, CREATE_TIMEOUT_MESSAGE, type ApiClient } from '../api/client';
import { AuthProvider } from '../auth/AuthContext';
import { Router } from '../router';
import { fakeApi } from '../test/fakeApi';
import { NewIncidentPage } from './NewIncidentPage';
import { validateIncident } from './validation';

function renderWith(api: ApiClient) {
  return render(
    <AuthProvider apiFactory={() => api}>
      <Router>
        <NewIncidentPage />
      </Router>
    </AuthProvider>,
  );
}

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/title/i), 'Payments failing');
  await user.selectOptions(screen.getByLabelText(/severity/i), 'HIGH');
  await user.type(screen.getByLabelText(/affected service/i), 'payment-service');
}

describe('validateIncident (same rules as CreateIncidentRequest)', () => {
  it('requires title, severity and service; limits lengths', () => {
    expect(validateIncident({ title: ' ', description: '', severity: '', affectedService: '' })).toEqual({
      title: 'Title is required.',
      severity: 'Choose a severity.',
      affectedService: 'Affected service is required.',
    });
    expect(validateIncident({ title: 'x'.repeat(256), description: 'd'.repeat(2001), severity: 'LOW', affectedService: 'svc' })).toEqual({
      title: 'Title must be at most 255 characters.',
      description: 'Description must be at most 2000 characters.',
    });
    expect(validateIncident({ title: 't', description: '', severity: 'CRITICAL', affectedService: 's' })).toEqual({});
  });
});

describe('NewIncidentPage', () => {
  it('shows client-side errors, marks fields invalid, focuses the first one and does not call the API', async () => {
    const user = userEvent.setup();
    const api = fakeApi();
    renderWith(api);

    await user.click(screen.getByRole('button', { name: /report incident/i }));

    const title = screen.getByLabelText(/title/i);
    expect(title).toHaveAttribute('aria-invalid', 'true');
    expect(title).toHaveFocus();
    expect(title).toHaveAccessibleDescription('Title is required.');
    expect(screen.getByText('Choose a severity.')).toBeInTheDocument();
    expect(api.createIncident).not.toHaveBeenCalled();
  });

  it('shows the server 400 field errors next to the fields', async () => {
    const user = userEvent.setup();
    const createIncident = vi.fn().mockRejectedValue(
      new ApiError(400, 'One or more fields are invalid.', {
        requestId: 'req-400',
        problem: { title: 'Validation failed', status: 400, errors: [{ field: 'affectedService', message: 'must not be blank' }] },
      }),
    );
    renderWith(fakeApi({ createIncident }));

    await fillValid(user);
    await user.click(screen.getByRole('button', { name: /report incident/i }));

    expect(await screen.findByText('must not be blank')).toBeInTheDocument();
    expect(screen.getByLabelText(/affected service/i)).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('alert')).toHaveTextContent('Validation failed');
    expect(screen.getByRole('alert')).toHaveTextContent('req-400');
  });

  it('shows the 429 rate-limit message with Retry-After', async () => {
    const user = userEvent.setup();
    const createIncident = vi.fn().mockRejectedValue(
      new ApiError(429, 'Rate limit of 30 incidents per minute exceeded for this tenant.', {
        requestId: 'req-429',
        retryAfterSeconds: 42,
        problem: { title: 'Too many requests', status: 429, limitPerMinute: 30 },
      }),
    );
    renderWith(fakeApi({ createIncident }));

    await fillValid(user);
    await user.click(screen.getByRole('button', { name: /report incident/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Too many requests');
    expect(alert).toHaveTextContent('Rate limit of 30 incidents per minute exceeded for this tenant.');
    expect(alert).toHaveTextContent('Try again in 42 s.');
    expect(alert).toHaveTextContent('req-429');
  });

  it('on a timeout says the incident may have been saved; sending again reuses the key, editing makes a new one', async () => {
    const user = userEvent.setup();
    const createIncident = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(0, CREATE_TIMEOUT_MESSAGE, { requestId: 'req-slow', timedOut: true }))
      .mockRejectedValueOnce(new ApiError(0, CREATE_TIMEOUT_MESSAGE, { requestId: 'req-slow-2', timedOut: true }))
      .mockResolvedValue({ id: '0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01' });
    renderWith(fakeApi({ createIncident }));
    await fillValid(user);

    await user.click(screen.getByRole('button', { name: /report incident/i }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('The incident may have been saved');
    expect(alert).toHaveTextContent('will not create a duplicate');
    expect(alert).toHaveTextContent('req-slow');

    await user.click(screen.getByRole('button', { name: /report incident/i })); // the same report again
    const [first, second] = createIncident.mock.calls.map((call) => call[1].idempotencyKey);
    expect(second).toBe(first);

    await user.type(screen.getByLabelText(/title/i), ' (EU)'); // an edit: a different report
    await user.click(screen.getByRole('button', { name: /report incident/i }));
    expect(createIncident.mock.calls[2][1].idempotencyKey).not.toBe(first);
  });

  it('suggests services seen in existing incidents (free text stays allowed) and sets the page title', async () => {
    const listIncidents = vi.fn().mockResolvedValue({
      items: [{ affectedService: 'search-service' }, { affectedService: 'checkout-api' }, { affectedService: 'search-service' }],
      page: 0,
      size: 100,
      totalElements: 3,
      totalPages: 1,
    });
    renderWith(fakeApi({ listIncidents }));

    const service = screen.getByLabelText(/affected service/i);
    await vi.waitFor(() => expect(service).toHaveAttribute('list', 'known-services'));
    const options = [...document.querySelectorAll('#known-services option')].map((o) => o.getAttribute('value'));
    expect(options).toEqual(['checkout-api', 'search-service']);
    expect(document.title).toBe('Report an incident — Incident Platform');
  });

  it('sends the trimmed request and navigates to the new incident', async () => {
    const user = userEvent.setup();
    const createIncident = vi.fn().mockResolvedValue({ id: '0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01' });
    renderWith(fakeApi({ createIncident }));

    await fillValid(user);
    await user.click(screen.getByRole('button', { name: /report incident/i }));

    expect(createIncident).toHaveBeenCalledWith(
      {
        title: 'Payments failing',
        description: undefined,
        severity: 'HIGH',
        affectedService: 'payment-service',
      },
      { idempotencyKey: expect.stringMatching(/.+/) },
    );
    expect(window.location.pathname).toBe('/incidents/0b9f4d6e-7a1c-4c2e-9d55-2f1e8a3b6c01');
  });
});
